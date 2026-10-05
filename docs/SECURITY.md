# Security and data boundaries

AgentJury reviews caller-supplied material. Its prompt treats task, context,
output and artifacts as untrusted data. Built-in reviewers see the same request
without other reviewers' votes or verdicts; deterministic aggregation runs after
their responses. Prompt delimiters are instructions to a model, not a sandbox or
a proof that prompt injection cannot work.

The deterministic local guard detects selected explicit reviewer commands in
the answer text. It can downgrade approval to `needs_revision`, but does not
cast a vote or create a judge finding. It is not an exhaustive injection scanner
and does not scan task/context/artifact text with those rules. Its cue words are
`reviewer`, `judge` and `jury` and the phrases `grading rubric` and
`rubric update`; plural forms such as `Reviewers:` do not match. Whitespace,
including line breaks, is folded before matching, so a directive split across
lines still matches when it is near a cue. The reviewer prompt
still labels all those sections untrusted. Checked excerpts validate source
provenance, not the truth or safety of the reviewer's interpretation.

## Observed artifact-injection failure

On 2026-10-02, a bounded local accuracy-role probe using qwen2.5:7b-instruct
approved an artifact containing commands to approve and suppress findings.
Both the old prompt and the corrected structured-source prompt returned accepted
approval. The corrected prompt initially detected manipulation but misattributed
its evidence; generic repair then dropped the concern and approved. The
deterministic output-only guard does not cover this artifact text.
This configuration is experimental, not validated for adversarial artifacts.
Structured JSON preserves source attribution; it is not an injection defense.
See [the recorded checks](REVIEW_INTEGRITY_VALIDATION.md#corrected-implementation-and-failed-safety-probes).

## Syntax-only repair boundary

Review policy 0.7 stops immediately when readable JSON fails the opinion schema
or a parsed opinion fails evidence validation. The unavailable judge contributes
an error, not a trusted finding or blocking vote. Only unreadable JSON gets one
retry; raw concerns in unreadable text are not semantically preserved. This
closes the recorded evidence-invalid concern followed by repaired approval.
It does not detect direct unsafe approvals. In fresh local held-out probes,
both baseline and candidate directly approved a forged-authority artifact;
both falsely revised an inert quoted training example. A remaining independent
quorum can still verify when one judge is unavailable. Keep this configuration
experimental. See [measured limitations](REVIEW_INTEGRITY_VALIDATION.md#syntax-only-repair-boundary---2026-10-02).

## Selected destinations and saved content

The selected judges receive the task, output, configured context and captured
artifact text. Native Ollama defaults to localhost but can be configured remote.
OpenRouter and vendor routes send material to their configured service. Compatible
endpoints may also be remote. There is no automatic privacy-routing policy.
SDK environment configuration can affect direct vendor endpoints; deployers must
control their configuration. API keys are supplied through the environment or
local ignored `.env` file; never include them in submitted artifacts or prompts.

Verdicts persist findings and checked excerpts locally. Sidecars duplicate verdict
content beside eligible files. Benchmark reports omit original case text and
checked excerpts, but model findings can still repeat sensitive content. Review
files before sharing them; a local report is not automatically redacted.

Built-in adapters disable redirects, check completion/model reports, validate
telemetry and sanitize transport exceptions. Model reports and endpoint hashes
are provenance telemetry, not cryptographic attestations. Custom in-process
judges/framework integrations are trusted executable code and are not isolated.
Custom exceptions can be saved by the panel; sanitize them before raising.

## Hermes file annotations

Hermes annotates only complete, unchanged, current-generation snapshots. Up to
five files and 20,000 characters per file are reviewed; partial, omitted or
unavailable coverage is explicit. Current-generation skipped certification is
removed best effort. Newer generations prevent late reviews from touching that
file, including across sessions sharing one Jury instance.

Content digests cover UTF-8 text after newline normalization and removal of
AgentJury frontmatter keys, not exact raw filesystem bytes. The verdict records
artifact identity, digest, request/run identity and coverage; it does not store
a full task-content hash. A matching digest alone
does not establish that the annotation applies to the latest task. Check the run
ID and coverage too. Storage failures are reported as `write_failed`; permissions
can prevent cleanup of an old annotation.

Checks and atomic replacements are serialized inside one plugin instance.
External writers and separate plugin processes do not share the lock, and a
check followed by replacement is not an atomic filesystem compare-and-swap.
Consumers must validate current content and run identity before trusting metadata.

## Code-change reviews

`agentjury change prepare` reads the repository locally and sends nothing. It
selects changed tracked files and untracked files that Git does not ignore;
selections must name changed paths inside the work tree. `.git/` and
`.agentjury/` are never included. Without reading their contents, it leaves out
files whose names indicate secrets (`.env*` except example, sample, template or
dist files; key and certificate files; credential stores such as `.npmrc`,
`.pypirc`, `.netrc`, `*.tfvars` and `*.tfstate`; `.ssh/`, `.gnupg/`,
`.aws/credentials`, `.docker/config.json`, `.kube/config` and
`.claude/settings.local.json`), symlinks (never followed), submodules,
lockfiles and unmerged files. Binary or non-UTF-8 content, files over 10 MB and
diffs over the per-file cap are also left out. Every omission is listed with its reason, and
the reviewers' scope notes name omitted paths without their contents.

A deterministic scan covers everything user-controlled that would be sent: the
task, each file's diff including removed and context lines, and the test log.
It looks for private-key blocks, common provider token formats, quoted
credential assignments and exact values of environment variables whose names
contain words such as KEY, TOKEN, SECRET, PASSWORD or AUTH. A match refuses the
preparation and is reported by source, line and rule (for a diff, the line
within that file's diff), never by value. `--allow-secret ID` accepts one
reported match for one preparation only. The scan is heuristic: a credential
without a recognizable shape passes it, so check the preview.

Task files and test logs must be regular files inside the repository with
names that do not indicate secrets. AgentJury never runs commands, so
pre-approving `prepare` in an agent cannot approve arbitrary execution. Test
logs are supplied evidence that AgentJury did not produce and cannot tie to the
reviewed bytes; logs older than the latest edit to a reviewed file are flagged.
Terminal escape sequences and control characters are removed from logs, and
model-written text is escaped when displayed.

`send` submits only the saved, previewed payload. It refuses before any provider
call when the confirmation code does not match the payload digest, the bundle
was edited, a reviewed file's bytes changed, the reviewer configuration (roles,
models, parameters, endpoint hosts or quorum) changed, the bundle was already
used or interrupted, or an identical payload was already reviewed. The digest
is a consistency check against accidental change, not a signature: anyone who
can write the repository can also prepare a different review.

The Claude Code plugin keeps the send step with the user. Its skills are
user-invoked only, never pre-approve `send`, and its `PreToolUse` hook denies
Claude-initiated `agentjury change send` commands, including through
`python -m agentjury.cli`. Hook and permission matching use command text; Claude
Code documents that this is not a security boundary around a program. The hook
prevents accidental or unrequested sends; it does not stop deliberate evasion.
A hook returning `ask` would not prompt in `bypassPermissions`, `dontAsk`, `-p` or
subagent contexts, so the plugin denies instead.

Prepared and sent reviews, including the full diff that was sent, stay under
`.agentjury/` in the repository root. When Git does not already ignore it,
`prepare` adds a self-ignoring `.agentjury/.gitignore`. Nothing is written into
reviewed files. The diff in `output` is subject to the local reviewer-command
guard, so code that addresses reviewers, such as tests of this project, can
become `needs_revision` with a visible warning.

## Adjudication exports

`agentjury adjudication export` is the one AgentJury artifact designed to be
shared. It is built from an explicit allowlist, and a test pins the exact set
of keys it can contain. Per verdict it carries identities (`run_id`,
`request_id`, `panel_id`), schema version, timestamps, task type, domain,
producer framework, provider and model, the vote counts, score, consensus,
diversity, confidence, status, local-check rule IDs, failed reviewers by name
and exception class (read from the panel's `name: Class: message` layout; an
error string in any other layout exports as nulls), artifact coverage counts
and the producer grade. Per
review: `review_id`, `config_id`, judge, role, provider, model, observed
model, vote, score, self-confidence, rubric version, prompt hash, allowlisted
parameters (`route`, `transport`, `format`, `endpoint_hash`,
`requested_model`, `completion_policy`, `timeout`, `max_tokens`, `effort`,
`thinking`, each checked against an expected shape), latency, token counts
and the review grade. Per finding: ID, severity, whether it had evidence, its
basis source and its grade. Per adjudication event: IDs, kind, time, the judge
name and the old and new labels.

It never carries the task, output, context, artifacts, finding text, excerpts,
reviewer reasons, error messages, notes, artifact names, file paths,
`producer.agent`, adjudicator identity, response IDs or other parameters. An
identity string with an unexpected shape is replaced by a stable digest and
counted; any other string outside the allowlist refuses the export with the
offending path. Judge, role, model, observed-model, requested-model,
task-type, domain and producer labels are operator-chosen free text, and local
model identifiers can name a path, so the command prints every distinct label
that leaves for review before sharing.
`endpoint_hash` is an unsalted hash of the endpoint URL: it confirms a guessed
endpoint but does not reveal one, and the same value is part of `config_id`.
Dropping adjudicator identity means grader disagreement cannot be measured
from an export. The `adjudication` commands read verdict directories and
modify nothing; corrupt records are skipped and named on standard error, and a
received export that is malformed is refused rather than counted. Printed
grading commands quote directory and identifier values for the shell (POSIX
quoting, or PowerShell quoting on Windows, where cmd.exe is not a target); a
record whose identifiers contain control characters, typographic quotes or,
on Windows, cmd.exe metacharacters gets a note instead of a command. A verdict
whose file name does not carry its run ID is named by its path.

## Human adjudication

All requested references/labels are validated before persistence. A directory
lock serializes writers. Verdict replacement first saves pending audit events;
history publication is idempotent by event ID. An interruption can leave pending
events visible in the verdict, and the next valid adjudication retries publication.
The CLI explicitly reports this state. These are recoverable separate files,
not one multi-file transaction. Preserve pending events and existing JSONL history.

The offline test guard blocks endpoints except ephemeral test-process servers.
`AGENTJURY_LIVE=1` intentionally disables that guard and enables live tests; use
it only for a separately authorized live run. See [evaluation](EVALUATION.md).
