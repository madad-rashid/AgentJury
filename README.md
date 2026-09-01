# AgentJury

[![tests](https://github.com/madad-rashid/AgentJury/actions/workflows/tests.yml/badge.svg)](https://github.com/madad-rashid/AgentJury/actions/workflows/tests.yml)

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

Judges vote ▲ approve, ▼ revise, or – abstain. Abstentions are recorded but never
counted as approval, and they count against quorum.

No single judge can block. `blocked` requires blocking findings from two
different providers; one blocking finding downgrades to `needs_revision`.

A panel needs a quorum of voters, by default a strict majority of requested
judges (1→1, 2→2, 3→2, 4→3, 5→3). A panel built from several providers must also
hear from at least two of them. Otherwise the status is `insufficient_jury` and
the votes are informational only.

Each judge call has a timeout, one retry on provider error, and one repair
round-trip if the reply is not valid JSON, after which the judge is marked
failed and the panel continues without it.

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

## Integrations

- **Hermes Agent**: `integrations/hermes/` is a Hermes plugin that reviews every
  substantial response, writes the verdict into the frontmatter of notes Hermes
  produced, and feeds findings back on the next turn. See its README.

## Status

Core frozen at v0.3. Collecting real verdicts through the Hermes integration.
Human adjudication and reviewer reputation follow once there is data to calibrate against.

## Protocol (schema 0.3)

Three objects, printable with `agentjury schema request` / `agentjury schema verdict`:

- `ReviewRequest` — the task, the agent's output, optional context and artifacts, plus
  `task_type`, `domain`, and the `producer` (agent, framework, provider, model)
- `Review` — one judge's independent vote, score, reason, and a list of `findings`
  each with a severity. Stands alone as a dataset row: carries `review_id`,
  `request_id`, `panel_id`, the judge's role, provider, model, prompt hash, rubric
  version, model `params` (effort, thinking, max_tokens), latency, and token usage,
  and leaves a `human_review` slot and a per-finding `adjudication` slot for later
  human grading
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
- [x] First framework integration: Hermes plugin (`integrations/hermes/`)
- [x] Review-event schema with telemetry and adjudication slots
- [x] Quorum, non-unilateral blocking, prompt-injection defence, custom roles
- [x] Abstain vote, provider floor, retry/repair/timeouts, CI
- [ ] Human adjudication command
- [ ] Reviewer reputation by task type, weighted by human agreement over time
- [ ] Jury diversity weighting from historical disagreement

## License

MIT
