# AgentJury v0.4.3, Public Alpha

AgentJury is an open-source peer-review layer for AI agents. It sends completed agent work to independent, blind AI reviewers and combines their opinions with deterministic aggregation rules.

This release prepares the project for broader public testing without changing the core jury behavior.

## Included

- clearer public-alpha README and quick start
- architecture diagram and design principles
- contributor guide for new judge providers and framework integrations
- PyPI-ready project metadata
- aligned package version metadata
- publishing and release checklist
- Hermes integration retained as the first live framework adapter
- human finding-level adjudication and append-only adjudication history retained

## Core behavior already available

- blind independent reviewers
- OpenAI and Anthropic judge adapters
- approve, revise, and abstain votes
- strict-majority quorum
- provider floor for multi-provider verification
- no unilateral blocking
- deterministic aggregation
- prompt-injection defenses
- retry and JSON repair handling
- stable request, run, review, configuration, and finding IDs
- custom reviewer roles
- Hermes background review integration

## Public alpha goal

The main goal now is real usage data. We want developers to run AgentJury on real agent workflows, adjudicate reviewer findings, and report false positives, missed errors, model instability, cost, latency, and integration friction.

Reviewer reputation and diversity weighting remain future work. They will be designed from observed human-adjudicated results rather than fixed assumptions.

## Install

AgentJury 0.4.3 is published on PyPI:

```bash
pip install "agentjury[all]"
```

Developers who want the latest unreleased code can install from GitHub instead:

```bash
pip install "agentjury[all] @ git+https://github.com/madad-rashid/AgentJury.git"
```

## Feedback

Please open issues at:

<https://github.com/madad-rashid/AgentJury/issues>

Do not include private company data, credentials, or API keys in public issues.
