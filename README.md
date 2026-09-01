# AgentJury

**An open peer-review and reputation layer for AI agents.**

When an agent finishes a task, AgentJury sends the task and its output to a
panel of independent AI judges. Each judge votes ▲ approve or ▼ revise, scores
the work, and explains why. AgentJury aggregates the votes into a verdict.

```
Controlled Institutional Private-Credit Pilot.md   +43
▲4 ▼1   score 8.7   consensus 80%   verified
```

Judges never see each other's votes before submitting their own, so they
can't anchor on one another.

## Status

Early development. The protocol is defined; judges and aggregator are next.

## Protocol

Three objects:

- `ReviewRequest` — the task, the agent's output, optional context and artifacts
- `Review` — one judge's independent vote, score, reason, and issues
- `Verdict` — the aggregate: votes, score, consensus, confidence, status

Any agent framework that can build a `ReviewRequest` can use AgentJury:
Hermes, Claude Code, Codex, CrewAI, LangGraph, AutoGen, or your own.

## Roadmap

- [x] Protocol schema
- [ ] Judge interface with OpenAI and Anthropic adapters
- [ ] Aggregator (votes, score, consensus, confidence)
- [ ] CLI: `agentjury review task.md output.md`
- [ ] First framework integration
- [ ] Reviewer reputation, weighted by human agreement over time

## License

MIT
