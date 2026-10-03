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

The normal test suite blocks network endpoints except ephemeral test servers.
Keep `AGENTJURY_LIVE=0` for offline validation. Change-review tests create
temporary Git repositories and need `git` on `PATH`; without it they are skipped. Native-route tests must mock the
transport or use their test HTTP server; never assume an absent SDK prevents a
native route from calling a local model.

## Benchmark cases and reports

`agentjury benchmark --panel SPEC` uses the packaged
`agentjury/data/starter.json` by default. Use `--cases FILE` for your own UTF-8
JSON pack with `schema_version: "1"`, unique case IDs, nonempty `task` and
`output`, optional `context`, and a `correct`, `flawed`, or `injected` label.
The file supplies the expected category; the benchmark cannot infer the
truth of arbitrary claims. A useful recommendation pack needs at least two
unambiguous cases in each category, including non-arithmetic constraints and
different prompt-injection wording.

The runner sends each distinct case/judge configuration once and replays
recorded reviews through the same aggregator as `review`. Keep the 20-call
default budget and resume behavior in mind when adding tests. Offline tests
should use fake judges and cover a cap reached during retry or JSON repair,
partial reports, recorded failures, and `--retry-errors`. Never make live
provider calls part of the normal suite.

Reports are saved under `.agentjury/benchmarks/`, which Git ignores. They
include model-generated reasons and findings; do not share them without
checking their contents. A case file goes to the selected model services.
The automatic suggestion is provisional: it needs a complete balanced pack,
two underlying providers, zero unsafe approvals, zero missed injected blocks,
at least 80% actionable verdicts and at least 80% correct-case verification.
It does not alter the default `review` panel. Free eligibility
requires explicit OpenRouter `:free` slugs or Ollama models. Run
`agentjury benchmark --help` for cap, resume, retry, and JSON options.

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

Native OpenRouter and Ollama transports live in `judges/openrouter.py` and
`judges/ollama.py`. Custom OpenAI-compatible endpoints use `judges/compatible.py`.
Validate complete responses and reported model identities before constructing a
`Completion`; preserve `observed_model`, sanitize errors and disallow redirects.
Panel syntax and judge
construction live in `agentjury/panel_config.py`, which is shared by the CLI
and Hermes. Add a separate adapter only when a provider needs a different API.
Never put a raw endpoint URL or API key in `Review.params` or `config_id`.
For routed models, preserve the underlying model vendor as `Review.provider`
when it can be identified; local and custom endpoints count as one provider.

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

The Hermes adapter in `integrations/hermes/` is the reference integration for
automatic review. `integrations/claude-code/` is the reference for explicit,
user-confirmed review: a Claude Code plugin of Markdown skills and a hook around
the framework-independent `agentjury change` commands. Its
`.claude-plugin/plugin.json` sets `version`, which pins installed users to that
version, so increase it whenever plugin files change. Run
`claude plugin validate --strict integrations/claude-code` and
`claude plugin validate --strict .` if you have Claude Code.

## Testing expectations

Use the [provider contracts](docs/PROVIDERS.md), [security boundaries](docs/SECURITY.md)
and [evaluation rules](docs/EVALUATION.md) when changing adapters or the process.
See [migration](docs/MIGRATION.md) before comparing older saved runs.

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
- rejection of duplicate configurations in a single panel
- artifact IDs, digest scope, partial coverage and stale annotation prevention
- adjudication prevalidation and idempotent recovery after audit interruption
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
