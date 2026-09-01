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

## Quick start

```
pip install -e ".[all]"
cp .env.example .env        # add your OPENAI_API_KEY and ANTHROPIC_API_KEY
agentjury review task.md output.md
```

```
▲2 ▼1  score 7.0  consensus 67%  verified
confidence 35%

▲  8  accuracy/openai        Sourced figure, drivers accurately characterized.
▼  5  critic/anthropic       Preqin citation has no year or report; 'rivals high-yield' is unsupported.
▲  8  executive/openai       Concise and investor-relevant.
```

Choose your own panel with `--panel accuracy:openai,critic:anthropic,evidence:anthropic,executive:openai`.
Run `agentjury roles` to see what each role looks for. Every verdict is saved to `.agentjury/verdicts/`.

## Status

Early development. Protocol, judges, aggregator, and CLI work. Framework
integrations and reviewer reputation are next.

## Protocol

Three objects:

- `ReviewRequest` — the task, the agent's output, optional context and artifacts
- `Review` — one judge's independent vote, score, reason, and issues
- `Verdict` — the aggregate: votes, score, consensus, confidence, status

Any agent framework that can build a `ReviewRequest` can use AgentJury:
Hermes, Claude Code, Codex, CrewAI, LangGraph, AutoGen, or your own.

## Roadmap

- [x] Protocol schema
- [x] Judge interface with OpenAI and Anthropic adapters
- [x] Aggregator (votes, score, consensus, confidence)
- [x] CLI: `agentjury review task.md output.md`
- [ ] First framework integration
- [ ] Reviewer reputation, weighted by human agreement over time

## License

MIT
