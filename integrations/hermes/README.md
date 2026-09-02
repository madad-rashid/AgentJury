# AgentJury for Hermes

Every substantial Hermes response is peer-reviewed by an independent panel of
AI judges. Verdicts are saved, written into the frontmatter of any markdown
notes Hermes produced that turn, and, if the panel asked for revisions, fed
back to Hermes at the start of the next turn.

```
---
agentjury_status: needs_revision
agentjury_votes: "▲1 ▼2"
agentjury_score: 6.3
agentjury_confidence: 0.42
agentjury_id: 9a9a900dc86b
---
```

## Install

Hermes has its own Python environment and its own home directory. Find both first:
`where hermes` (Windows) or `which hermes` shows the launcher; the venv is next to it.
The home directory is the one containing Hermes's `config.yaml` and `.env`
(on Windows often `%LOCALAPPDATA%\hermes`, on Linux/macOS usually `~/.hermes`).

1. Install AgentJury and the judge SDKs into Hermes's Python. If the venv was made by `uv`:
   `uv pip install --python <hermes-venv>/Scripts/python.exe git+https://github.com/madad-rashid/AgentJury openai anthropic`
   otherwise `<hermes-python> -m pip install ...` with the same packages.
2. Link or copy this folder to `<hermes-home>/plugins/agentjury/`
   (Windows: `mklink /J <hermes-home>\plugins\agentjury <path-to-this-folder>`).
3. Add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_WORKSPACE_ID` if your key needs it,
   to `<hermes-home>/.env`.
4. `hermes plugins doctor <hermes-home>/plugins/agentjury`, then `hermes plugins enable agentjury`.
   Decline the tool-override capability; AgentJury never replaces built-in tools.
5. Start `hermes`, ask something substantial, wait ~20s, type `/jury`.
   Troubleshoot with `hermes logs --level INFO | findstr /i agentjury` (Windows) or `| grep -i agentjury`.

## Configure

In `<hermes-home>/config.yaml`:

```yaml
plugins:
  entries:
    agentjury:
      settings:
        panel: "accuracy:openai,domain_expert:anthropic,critic:anthropic,executive:openai"
        roles_file: "/path/to/roles.json"       # defines domain_expert
        context_file: "/path/to/madad-context.md"
        task_type: "research"
        domain: "private_credit"
        min_chars: 400
        frontmatter: true
        sidecar: true
        feedback: true
```

## Use

Type `/jury` in any session to see the latest verdict, or `/jury <request_id>`
for a saved one. Verdict JSON accumulates in `<HERMES_HOME>/plugin-data/agentjury/verdicts/`.
