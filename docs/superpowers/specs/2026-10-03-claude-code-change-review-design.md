# Claude Code Change Review

## Purpose and decisions

AgentJury's first integration, Hermes, reviews substantial responses
automatically. Coding agents need the opposite: an explicit, on-demand review
of a selected code change, with the user seeing exactly what leaves the machine
before anything is sent. The user approved this design on 2026-10-03 with three
decisions:

- **The user sends.** Claude Code prepares and previews a review, but the user
  runs the send command. A plugin hook denies Claude-initiated sends.
- **Framework-independent core.** The logic is a new `agentjury change` command
  group in the package, usable from any terminal, agent or CI job. The Claude
  Code plugin is Markdown and JSON around those commands.
- **Code roles by default.** New `correctness`, `security` and `tests` roles
  ship as packaged custom roles. The default panel is
  `correctness:openai,security:anthropic,tests:openai`, the providers the
  existing default panel already requires.

Deterministic aggregation, quorum, the provider floor, blocking rules, the
reviewer rubric and the protocol schema (0.7) are unchanged. Reputation
weighting stays inactive and the confidence index stays a heuristic.

## Claude Code facts that shape the design

Checked against the official documentation on 2026-10-03:

- A skill with `disable-model-invocation: true` runs only when the user types
  it; its description stays out of Claude's context. `allowed-tools`
  pre-approves tools for the invoking turn only, and deny or ask rules still
  win. `` !`command` `` lines run before Claude sees the skill and abort it on
  failure.
- Plugins can ship skills and `hooks/hooks.json` but not permission rules.
- A `PreToolUse` hook returning `ask` lets the call through without a prompt in
  `bypassPermissions`, `dontAsk`, `-p` and subagent contexts. `deny` holds in
  every mode. The hook `if` field filters by permission-rule syntax.
- Bash rule and hook matching use command text and are not a security boundary
  around a program.
- Shell mode (`! command`) runs without going through Claude.
- Cloud sessions do not install plugins, and their default network allowlist
  does not name OpenAI or OpenRouter hosts.

## Command contract

`agentjury change candidates [--base REV]` lists changed tracked files and
untracked files that Git does not ignore, marking default exclusions. It reads
no file contents and always exits 0 inside a Git work tree.

`agentjury change prepare` builds a `ReviewRequest` locally and makes no
network call:

- `task`: the user-confirmed task text (`--task` or `--task-file`).
- `output`: the unified diff of the selected files against the base commit
  (default `HEAD`), covering staged and unstaged edits and selected untracked
  files. Placing the diff in `output` keeps the existing local
  reviewer-command guard in force.
- `context`: generated review scope (base commit, reviewed and excluded files,
  a statement that reviewers cannot run code) and optional test evidence with
  its provenance.
- No artifacts, so the plain-text prompt format is used.
- `task_type="code_change"`; producer fields come from flags.

It constructs the panel without contacting a provider to record each judge's
role, route, model, destination host and configuration ID. It writes a pending
bundle and a preview under `.agentjury/changes/pending/<request_id>/`, prints a
manifest and the exact send command, and exits 0. Any refusal exits 6 and
writes nothing.

`agentjury change send ID --confirm CODE` sends a prepared bundle once. It
refuses with exit 6, before any provider call, when the confirmation code does
not match the payload digest, a reviewed file changed since preparation, the
reviewer configuration changed, the bundle was edited, the bundle was already
used or is being sent, or an identical payload was already reviewed (unless
`--allow-repeat`). Otherwise it runs the existing `Panel.review`, saves the
verdict to the verdict directory, writes the snapshot binding, deletes the
pending bundle, reports whether reviewed files changed while the review ran,
and exits with the existing verdict codes 0 to 3. If saving fails after the
review, the lock stays so the bundle is neither resent nor listed as unsent.

`agentjury change status [RUN]` shows a saved review with its snapshot state:
exit 0 when current, 7 when stale. Adjudication uses the existing
`agentjury verdicts` and `agentjury adjudicate` commands unchanged.

## Privacy safeguards

Only the diff of selected changed files is sent. Selections must name changed
files inside the repository; Git-ignored untracked files are never candidates,
and `.git/` and `.agentjury/` are always excluded. Files are listed as not sent,
with a reason and without reading their contents, when their names indicate
secrets (`.env*` except example/sample/template files, private keys and
certificates, credential stores such as `.npmrc`, `.pypirc`, `.netrc`,
`*.tfvars`, `*.tfstate`) or when they are symlinks (never followed),
submodules, lockfiles or unmerged (detected from index stages, because a diff
against a commit reports conflicts as modifications). Binary or non-UTF-8
content, files over 10 MB and diffs over the per-file cap are also listed as not
sent. Preparation stops as soon as the selection exceeds the total cap.

A deterministic secret scan covers every user-controlled text that would be
sent: the task, each file's diff including removed and context lines, and the
test log. It detects private-key blocks, common provider token formats, quoted
credential assignments and exact values of secret-named environment variables.
Any match refuses preparation and reports source, line and rule, never the
value. A specific match can be accepted for one preparation with
`--allow-secret ID`. The scan is heuristic.

Task files and test logs must be inside the repository. AgentJury never runs
commands, so pre-approving `prepare` never pre-approves arbitrary execution.
Test logs are labelled as supplied evidence that AgentJury did not run and
cannot tie to the snapshot; a log older than the latest edit to a reviewed file
is flagged. ANSI sequences and other control characters are removed from logs.

Everything is stored under `.agentjury/` in the repository root. If Git does not
already ignore that directory, preparation adds a self-ignoring
`.agentjury/.gitignore`. Nothing is written into reviewed files. API keys are
never printed or stored; the preview names each destination host.

## Snapshot binding and staleness

The snapshot records the resolved base commit, `HEAD` at preparation and, for
each reviewed file, its change type, the SHA-256 of its working-tree bytes (or
`deleted`), its Git blob ID from `git hash-object` (no write) and its diff
offsets. The payload digest is SHA-256 over the exact user prompt every judge
receives, each judge's configuration ID, model and destination host, and the
quorum. The confirmation code is its first 16 hex characters.

After a send, `.agentjury/changes/reviews/<run_id>.json` stores the bundle,
including the request actually sent. It lives outside the verdict directory
because `agentjury verdicts` and `agentjury adjudicate` parse every JSON file
there. The verdict's existing `artifact_coverage` gains one entry per file with
the path, digest and coverage (`full` for reviewed files, `omitted` for
excluded ones) and `annotation_status="not_requested"`, as Hermes already uses
that field.

A review is current only while every reviewed file has the same bytes (or is
still absent). Otherwise it is stale and the changed files are listed. Line
ending rewrites therefore count as changes. Status also reports when the
reviewed content matches `HEAD`, when `HEAD` moved and how many other changed
files the review does not cover. Staleness is computed whenever a review is
displayed; there is no background hook.

## Claude Code plugin

`integrations/claude-code/` is a plugin named `agentjury`, listed by a
repository-root `.claude-plugin/marketplace.json`:

- `/agentjury:review` drafts or accepts the task, asks the user to confirm the
  task and file selection, optionally captures real test output, runs
  `prepare`, shows the manifest and tells the user to run the printed send
  command themselves. After the verdict it summarizes findings as reviewers'
  claims and makes no edits, commits or further reviews unless asked.
- `/agentjury:status` shows `agentjury change status`.
- `/agentjury:adjudicate` records only grades the user states, by showing and
  then running the existing `agentjury adjudicate` command.
- `hooks/hooks.json` denies Claude-initiated `agentjury change send` commands
  for the Bash and PowerShell tools. It prints a fixed deny decision and needs
  no interpreter.

All skills set `disable-model-invocation: true`; none pre-approves `send` or
`adjudicate`.

## Verification

Offline tests use temporary Git repositories, fake judges through a panel
factory seam and the existing network guard, on Linux and Windows CI. They
cover change discovery and selection, every exclusion class, the secret scan,
preview equality with the prompt judges receive, absence of configured keys
from all output, refusals with zero judge calls, a successful send followed by
existing listing and adjudication, aggregation invariants through this path,
current and stale status, escaped display of model text and static checks of
the plugin files. Run the full suite, `python -m build` and `twine check`.
No live provider call is part of this change.

## Limits

Reviewer quality on code is unmeasured; no benchmark cases cover code.
`verified` means the configured jury approved the supplied diff, not that the
code is correct. Multi-line excerpts from a diff must include diff markers, so
the roles ask for single-line excerpts. Anthropic judges reviewing
Claude-written code may favour it; producer fields record this but do not
correct it. The local guard can flag code that addresses reviewers. Text-based
hooks prevent accidental sends, not deliberate evasion. Shell mode is documented
for the interactive CLI; other surfaces may need a terminal. Cloud sessions are
not supported in this version. PyPI users need the next release.
