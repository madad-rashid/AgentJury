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

1. Install AgentJury into the Python that runs Hermes:
   `pip install git+https://github.com/madad-rashid/AgentJury`
2. Copy or symlink this folder to `~/.hermes/plugins/agentjury/`
3. Make sure `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID`
   if your key needs it) are in `~/.hermes/.env`
4. `hermes plugins doctor ~/.hermes/plugins/agentjury` then `hermes plugins enable agentjury`

## Configure

In `~/.hermes/config.yaml`:

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
