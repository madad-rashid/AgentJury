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
▲2 ▼1  score 7.0  consensus 67%  diversity 67%  jury 3/3  verified
jury confidence index 35%  (heuristic, not a probability)

▲  8  accuracy/openai        Sourced figure, drivers accurately characterized.
▼  5  critic/anthropic       Preqin citation has no year or report; 'rivals high-yield' is unsupported.
▲  8  executive/openai       Concise and investor-relevant.
```

Choose your own panel with `--panel accuracy:openai,critic:anthropic,evidence:anthropic,executive:openai`.
Run `agentjury roles` to see what each role looks for. Every verdict is saved to `.agentjury/verdicts/`.

## How a verdict is reached

No single judge can block. `blocked` requires blocking findings from two
different providers; one blocking finding downgrades to `needs_revision`.
A panel needs a quorum (default: a majority of requested judges) or the status is
`insufficient_jury` and the votes are informational only.

Exit codes: `0` verified, `1` needs_revision, `2` blocked, `3` insufficient_jury.

The confidence figure is a heuristic index, not a calibrated probability. It will
be calibrated against human adjudication once enough exists.

Judges treat everything they review as untrusted data. Instructions hidden inside
the output are reported as a blocking finding. `tests/test_adversarial_live.py`
attacks the jury with `examples/injected_output.md`; run it with `AGENTJURY_LIVE=1`.

## Custom roles

Give a jury domain expertise with a JSON file of `{"role_name": "description"}`:

```
agentjury review task.md output.md --roles examples/roles.json --panel accuracy:openai,domain_expert:anthropic,executive:openai
```

## Status

Early development. Protocol, judges, aggregator, quorum, and CLI work. Framework
integrations and reviewer reputation are next.

## Protocol (schema 0.2)

Three objects, printable with `agentjury schema request` / `agentjury schema verdict`:

- `ReviewRequest` — the task, the agent's output, optional context and artifacts, plus
  `task_type`, `domain`, and the `producer` (agent, framework, provider, model)
- `Review` — one judge's independent vote, score, reason, and a list of `findings`
  each with a severity. Also records the judge's role, provider, model, prompt hash,
  rubric version, latency, and token usage, and leaves a `human_review` slot and a
  per-finding `adjudication` slot for later human grading
- `Verdict` — the aggregate: votes, score, consensus, diversity, confidence, status

Every field reputation will need is recorded from the first review. Reputation
weighting itself is not active yet.

Any agent framework that can build a `ReviewRequest` can use AgentJury:
Hermes, Claude Code, Codex, CrewAI, LangGraph, AutoGen, or your own.

## Roadmap

- [x] Protocol schema
- [x] Judge interface with OpenAI and Anthropic adapters
- [x] Aggregator (votes, score, consensus, confidence)
- [x] CLI: `agentjury review task.md output.md`
- [ ] First framework integration
- [x] Review-event schema with telemetry and adjudication slots
- [x] Quorum, non-unilateral blocking, prompt-injection defence, custom roles
- [ ] Human adjudication command
- [ ] Reviewer reputation by task type, weighted by human agreement over time
- [ ] Jury diversity weighting from historical disagreement

## License

MIT
