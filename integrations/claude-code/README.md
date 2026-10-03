# AgentJury for Claude Code

Ask a blind AgentJury panel to review a code change you made with Claude Code.
Nothing is reviewed automatically. You start a review, see exactly what would
be sent and to whom, and run the send command yourself. The verdict is an
ordinary AgentJury verdict: same aggregation, quorum, provider-diversity and
blocking rules, and the same human adjudication.

```text
/agentjury:review Add retry with backoff to the upload client
  -> Claude confirms the task and files with you, then prepares a preview
! agentjury change send 9a9a900dc86b --confirm 3f9a1c2b7d4e5f60
  -> ▲2 ▼1  score 7.0  consensus 67%  diversity 67%  jury 3/3  verified
/agentjury:status
  -> Code snapshot: CURRENT (or STALE after an edit)
/agentjury:adjudicate correctness finding 1 wrong, the timeout is configurable
```

## Install

1. Install AgentJury so that `agentjury` is on the `PATH` of the shell Claude
   Code uses. A tool installer keeps it isolated from your project:

   ```bash
   uv tool install "agentjury[all] @ git+https://github.com/madad-rashid/AgentJury"
   # or
   pipx install "git+https://github.com/madad-rashid/AgentJury"
   pipx inject agentjury openai anthropic
   ```

   `agentjury change` is not in the published 0.5.0 package; until the next
   release, install from `main` as above. Check with `agentjury change --help`.
2. Set provider keys for the default panel (`OPENAI_API_KEY`,
   `ANTHROPIC_API_KEY`) in the environment Claude Code starts from, or choose
   another panel below. Do not keep keys in files you review.
3. In Claude Code, add this repository as a plugin marketplace and install the
   plugin:

   ```text
   /plugin marketplace add madad-rashid/AgentJury
   /plugin install agentjury@agentjury
   ```

   To try a local checkout instead, start Claude Code with
   `claude --plugin-dir <path-to-AgentJury>/integrations/claude-code`.

## Use

`/agentjury:review [what the change should do]`

1. Claude lists your changed files and confirms the task text and file
   selection with you.
2. Optionally, Claude reruns your tests and saves their real output as test
   evidence. It never writes test output itself.
3. Claude runs `agentjury change prepare`, which builds the review locally and
   sends nothing. It prints the reviewers and destination hosts, the files sent
   and not sent (with reasons), the secret-scan result and a confirmation code.
   `.agentjury/changes/pending/<id>/preview.md` holds the exact text each
   reviewer would receive.
4. **You send it** by typing the printed command after `!`, or by running it in
   a terminal in the repository:
   `agentjury change send <id> --confirm <code>`. Claude cannot send it: the
   plugin's hook denies that command when Claude runs it.
5. The verdict shows numbered findings with file hints. Claude summarizes it and
   does not edit, commit or start another review unless you ask.

`/agentjury:status [run-id]` shows a saved review and whether the reviewed code
is unchanged. `/agentjury:adjudicate` records grades you state, through the
existing `agentjury adjudicate` command.

All three skills are user-invoked only (`disable-model-invocation: true`).

## Configure

| Setting | Effect |
| --- | --- |
| `AGENTJURY_CHANGE_PANEL` or `--panel` | Reviewers; default `correctness:openai,security:anthropic,tests:openai` |
| `--roles FILE` or `AGENTJURY_ROLES` | Extra roles; the packaged `correctness`, `security` and `tests` roles are always available |
| `--base REV` | Commit to compare with (default `HEAD`); staged, unstaged and selected untracked files are included |
| `AGENTJURY_VERDICT_DIR` or `--dir` | Where `send` saves verdicts (default `.agentjury/verdicts` in the repository) |

Panels use the same `role:provider[:model]` syntax as `agentjury review`,
including OpenRouter, Ollama and compatible endpoints. See
[providers](../../docs/PROVIDERS.md).

## What is sent and stored

Only the diff of the selected changed files, the task text, generated scope
notes and an optional test log are sent, to the reviewers named in the preview.
Files with secret-bearing names (`.env`, keys, credential stores), symlinks,
submodules, lockfiles, binary or non-UTF-8 files and very large diffs are not
sent, and are listed with a reason. A local secret scan refuses to prepare a
review when the payload contains something that looks like a credential; it
reports the location, never the value. See [security](../../docs/SECURITY.md).

Everything stays under `.agentjury/` in your repository. If Git does not
already ignore that directory, AgentJury adds `.agentjury/.gitignore`. Nothing is
written into your source files.

A review is bound to the exact bytes of the files it covered. `send` refuses if
anything changed since the preview, and `status` reports STALE after any later
edit to a reviewed file.

## Limits

- `verified` means this panel approved the supplied diff. Reviewers cannot run
  your code, and no benchmark yet measures reviewer accuracy on code. The
  confidence index is a heuristic, not a probability.
- The send guard matches command text. It prevents accidental or unrequested
  sends by Claude; it is not a barrier against deliberate evasion. It also
  blocks harmless commands that contain the text `agentjury change send `, such
  as a search for it.
- Shell mode (`!`) is documented for the interactive Claude Code CLI. Elsewhere,
  run the send command in a terminal. Windows without Git Bash is untested.
- Claude Code cloud sessions do not install plugins, and their default network
  allowlist does not include most reviewer providers. This version targets local
  sessions.
- Code that addresses reviewers, such as AgentJury's own tests, can trigger the
  local reviewer-command check and become `needs_revision`.
