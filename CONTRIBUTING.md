# Contributing to AgentJury

Thanks for helping test and improve AgentJury.

AgentJury is in public alpha. Contributions are especially useful when they improve reviewer reliability, provider diversity, integration quality, reproducibility, or the evidence used for future reputation scoring.

## Development setup

Requirements:

- Python 3.11 or newer
- Git
- provider API keys only if you run live judge tests

Clone the repository and install the package in editable mode:

```bash
git clone https://github.com/madad-rashid/AgentJury.git
cd AgentJury
python -m venv .venv
```

Activate the environment, then install development dependencies:

```bash
pip install -e ".[all,dev]"
```

Run the test suite:

```bash
python -m pytest tests -q
```

The normal test suite should not require live model calls.

## Live adversarial test

The live adversarial test sends an injected output to configured providers. It costs API tokens and is disabled by default.

```bash
AGENTJURY_LIVE=1 python -m pytest tests/test_adversarial_live.py -q
```

Set the required provider keys before running it.

## Adding a judge provider

A provider adapter should stay thin. The shared `Judge` class owns reviewer prompting, retry behavior, JSON repair, parsing, IDs, and review construction.

To add a provider:

1. Add a module under `agentjury/judges/`.
2. Subclass `Judge`.
3. Set a stable `provider` name.
4. Implement `complete(system, user) -> Completion`.
5. Return token usage and provider response ID when available.
6. Record model parameters that materially affect judging behavior in `self.params`.
7. Disable hidden SDK retries where practical so AgentJury's retry policy stays observable.
8. Add unit tests for success, provider failure, malformed output, retry, and telemetry.

Provider adapters must not expose other reviewers' votes to the model. Blind review is a core protocol property.

## Adding a reviewer role

You often do not need a code change. Custom roles can be loaded from JSON:

```json
{
  "security": "Check for security vulnerabilities and unsafe assumptions.",
  "finance": "Check calculations, financial assumptions, and unsupported claims."
}
```

Then run:

```bash
agentjury review task.md output.md \
  --roles roles.json \
  --panel security:openai,finance:anthropic
```

A built-in role belongs in code only when it is broadly useful across domains.

## Adding an agent-framework integration

Integrations should remain adapters around the core protocol.

A good integration should:

1. capture the original task and final agent output
2. collect only relevant artifacts
3. build a `ReviewRequest`
4. run a configured `Panel`
5. persist the exact `Verdict`
6. surface the verdict without changing its meaning
7. preserve `request_id`, `run_id`, `review_id`, `config_id`, and finding IDs
8. keep private content handling explicit

Do not put framework-specific behavior into the aggregation core unless the protocol itself requires a change.

The Hermes adapter in `integrations/hermes/` is the reference integration.

## Testing expectations

For behavior changes, add or update tests that show the intended behavior and the failure case being fixed.

Important invariants include:

- strict-majority quorum
- abstentions never counting as approval
- provider floor for multi-provider verification
- no unilateral blocking
- blocking derived from findings
- blind reviewer independence
- deterministic aggregation
- stable provenance IDs
- reviewer configuration identity including material model parameters
- failed judges reducing available quorum rather than being treated as approval

## Pull requests

Keep pull requests focused. Explain:

- what problem the change solves
- why the change belongs in AgentJury
- how you tested it
- whether it changes the protocol or schema
- whether it changes provider cost, latency, or privacy behavior

Before opening a pull request, run:

```bash
python -m pytest tests -q
```

If the change touches a live provider adapter, include the provider and model used for manual validation, but never include API keys.

## Reporting jury failures

Real failures are valuable. If a reviewer makes a false finding, flips unexpectedly across configurations, misses an obvious error, or disagrees with a human adjudicator, open an issue with the smallest reproducible example you are comfortable sharing.

Useful details include:

- AgentJury version
- task type and domain
- reviewer provider, model, role, and relevant parameters
- vote and score
- which finding was wrong or missed
- whether the human adjudicator agreed or disagreed

Do not post proprietary source material unless you have permission to make it public.

## License

By contributing, you agree that your contribution will be licensed under the repository's MIT License.
