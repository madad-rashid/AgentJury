# Provider Access for AgentJury Phase Two

## Purpose and success criteria

Make AgentJury easier to try with either one OpenRouter key or a locally running Ollama model, while retaining direct OpenAI and Anthropic support. A user can also point AgentJury at another OpenAI-compatible chat endpoint, such as LM Studio. The CLI and Hermes integration must interpret the same panel configuration and produce the same verdict semantics.

Success means a user can select named models in a panel, complete a review through OpenRouter or a local server, see an auditable model and route identity in the saved verdict, and receive a clear failure when a key, model, or server is unavailable. Existing two-field panel specifications continue to work.

## Scope

This phase adds OpenRouter, Ollama, and one configurable OpenAI-compatible endpoint. It does not add reviewer reputation, weighted voting, calibrated confidence, model discovery, automatic model selection, routing fallbacks, or a user interface. The default panel stays unchanged; the new quick starts use explicit `--panel` settings.

## Approach

Use one shared adapter built on the optional `openai` Python SDK's Chat Completions API. OpenRouter and Ollama document compatible endpoints, so separate transport implementations would duplicate request, response, and telemetry handling. Named configurations supply the endpoint and credential rules; a custom configuration accepts a user-supplied endpoint.

The shared adapter subclasses `Judge`. The existing base class continues to own prompt construction, independent reviews, retries, JSON repair, parsing, provenance IDs, and review construction. The adapter only configures the client and implements `complete(system, user) -> Completion`. SDK retries remain disabled so AgentJury's retry count remains observable.

## Panel configuration and credentials

Panel entries use `role:provider[:model]`. Split each entry at only the first two colons so model names such as `qwen3:8b` remain intact. The existing `role:openai` and `role:anthropic` forms keep their defaults. An explicit third field also selects a model for those direct providers. `openrouter`, `ollama`, and `compatible` require an explicit nonempty model.

Examples:

```text
accuracy:openrouter:openai/<model>,critic:openrouter:anthropic/<model>
accuracy:ollama:qwen3:8b,critic:ollama:qwen3:8b
accuracy:compatible:<model>
```

OpenRouter uses `OPENROUTER_API_KEY` and `https://openrouter.ai/api/v1`. Missing keys fail during panel construction with a clear instruction. OpenRouter model names must have a nonempty `vendor/model` form: the vendor contains only letters, digits, dots, underscores, or hyphens and starts with a letter or digit. Dynamic aliases such as `~openai/...`, the `openrouter/*` router namespace, and names without a vendor are rejected because they cannot establish a stable model-provider identity for the jury rule.

Ollama uses `AGENTJURY_OLLAMA_BASE_URL`, defaulting to `http://127.0.0.1:11434/v1`, and needs no user-supplied key. The SDK may receive an internal placeholder key, which is never exposed in a verdict. The custom endpoint requires `AGENTJURY_COMPATIBLE_BASE_URL` and accepts an optional `AGENTJURY_COMPATIBLE_API_KEY`. No endpoint or key is inferred from OpenAI's environment variables. Configured endpoint URLs must be absolute HTTP(S) URLs without embedded credentials, query strings, or fragments.

The CLI and Hermes both call a shared panel parser and judge factory. Their different configuration sources remain as they are: CLI arguments and environment defaults for the CLI; Hermes settings for Hermes. Invalid roles, providers, model fields, and missing endpoint settings receive actionable errors.

## Identity, diversity, and saved data

`Review.model` stores the exact requested model. OpenRouter derives `Review.provider` from the explicit vendor prefix, so `openai/...` and `anthropic/...` count as two model providers, while two `openai/...` models count as one. A direct OpenAI judge and an OpenRouter-routed `openai/...` judge also count as one provider for diversity. Ollama and the custom endpoint each report one stable provider identity regardless of model name; merely changing local model names does not create multi-provider independence. When the custom endpoint URL matches the configured Ollama URL after normalization, both routes report `ollama` as their provider while retaining distinct route metadata.

The route name (`openrouter`, `ollama`, or `compatible`) and a SHA-256 fingerprint of the normalized base URL are recorded in `Review.params` and therefore affect `config_id`. API keys and raw endpoint URLs are not stored. New-route judge names use `role/route/model` so two entries with the same role and underlying provider remain distinguishable. Panel output remains in configured order even when judges finish in a different order.

The existing quorum, provider floor, blocking, and status rules remain unchanged. No schema field or schema version changes are required; this design fills existing `provider`, `model`, and `params` fields.

## Failure behavior

A missing OpenRouter key, missing custom endpoint URL, or malformed panel entry fails before making review calls. An unreachable endpoint, rejected model, or invalid response is recorded as that judge's error after the existing retry and repair policy. Other judges can still finish. The resulting verdict becomes `insufficient_jury` whenever successful non-abstaining reviews cannot meet quorum or the requested provider floor.

Error text should identify the selected route and model without printing secrets. The adapter wraps transport and HTTP errors with a safe summary (route, model, error class, and HTTP status when present) rather than copying arbitrary SDK exception text that could include credentials. The custom endpoint may be remote and is explicitly chosen by the user; documentation explains that reviewed task content is sent to that endpoint. OpenRouter sends the reviewed content to OpenRouter's service. Ollama's default endpoint is local.

## Files and boundaries

- `agentjury/judges/compatible.py`: shared Chat Completions adapter and named endpoint configuration.
- `agentjury/panel_config.py`: panel grammar and provider factory shared by CLI and Hermes.
- `agentjury/judges/__init__.py`: public constructors for the new routes.
- `agentjury/cli.py` and `integrations/hermes/jury.py`: delegate panel construction to the shared parser.
- `agentjury/panel.py`: retain configured output order when names repeat.
- `agentjury/protocol.py`: clarify the meaning of existing provider and route metadata without adding fields.
- `README.md`, `.env.example`, `CONTRIBUTING.md`, and `integrations/hermes/README.md`: one-key, local, and custom-endpoint quick starts and their configuration requirements.
- Tests under `tests/`: parser compatibility, adapter requests and telemetry, provenance and diversity, failure handling, and CLI/Hermes parity.

## Verification

Automated tests use a fake SDK client or local in-process response server, so the normal test suite needs no paid model call. Tests cover old and new panel syntax, model names containing colons, endpoint and key validation, request shape, usage and response IDs, malformed replies, retry behavior, configured order, and provider-floor outcomes for mixed OpenRouter, direct, Ollama, and custom panels. Run the existing full test suite and package build. A live OpenRouter or Ollama smoke test is optional when the respective service and credentials are available; lack of either does not block the offline verification.

## External API references

- [OpenRouter quick start](https://openrouter.ai/docs/quickstart) documents its OpenAI-compatible API and Python SDK configuration.
- [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx) documents its local Chat Completions endpoint.
