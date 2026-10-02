# Provider routes

This guide describes the draft `fix/review-integrity` branch, not the older
published package. Install the branch as described in [migration](MIGRATION.md).
Panel syntax is `role:provider[:model]`, shared by the CLI and Hermes. Empty
entries and a trailing comma are tolerated; an empty panel is rejected.

| Route | Model selection | Runtime dependency | Destination / identity |
| --- | --- | --- | --- |
| `openai` | Explicit model, or adapter default `gpt-5.6` | OpenAI SDK >=1.55.3 | SDK-configured OpenAI endpoint; provider `openai` |
| `anthropic` | Explicit model, or adapter default `claude-sonnet-5` | Anthropic SDK >=1.11.0 | SDK-configured Anthropic endpoint; provider `anthropic` |
| `openrouter` | Explicit fixed `vendor/model[:variant]`, or `AGENTJURY_OPENROUTER_MODEL` | Standard library | OpenRouter HTTPS chat completions; provider is model vendor prefix |
| `ollama` | Explicit installed model, or `AGENTJURY_OLLAMA_MODEL` | Standard library | Native `/api/chat`; all Ollama models count as provider `ollama` |
| `compatible` | Explicit model required | OpenAI SDK >=1.55.3 | `AGENTJURY_COMPATIBLE_BASE_URL`; provider `compatible`, or `ollama` when it matches that configured endpoint |

Model names in examples are configuration examples, not a verified availability
catalog or a recommendation. Check the selected service before an authorized
live run. Changing from the PR 5 SDK routes to native transports changes reviewer
configuration IDs; historical reputation and benchmark jobs must remain distinct.

## Configuration

OpenRouter needs `OPENROUTER_API_KEY`. Automatic `openrouter/*` aliases are
rejected; choose fixed model slugs. The full request, including `:free` or other
routing variant, is retained in `params.requested_model`. `Review.model` records
the canonical vendor/model and `observed_model` records the endpoint report.
The returned model must match the requested variant or its exact base slug.

Ollama defaults to `http://127.0.0.1:11434`. Set `AGENTJURY_OLLAMA_URL` to change
the root. The older `AGENTJURY_OLLAMA_BASE_URL` remains accepted, including `/v1`,
which is removed before calling `/api/chat`; the new variable takes precedence.
Two configured names differing only by omission of `:latest` share reviewer
identity within the same route. Native and compatible transports retain their
different configuration identities because their request format differs.

Compatible endpoints use an absolute HTTP(S) URL without user-info, query,
fragment or whitespace. `AGENTJURY_COMPATIBLE_API_KEY` is optional. Equivalent
scheme/host case, default ports and trailing slashes are normalized for endpoint
identity. Paths remain case-sensitive; `localhost` and `127.0.0.1` are not
guessed equivalent. A compatible `/v1` endpoint on the configured Ollama root
counts as Ollama rather than creating another provider.

Direct vendor calls accept the exact requested model or, for an undated alias,
that same name with a valid dated snapshot suffix. Explicit snapshot requests
must match exactly. Unsupported aliases or missing required model reports fail
closed. Custom compatible endpoints may omit their model report; it is then
unknown, rather than asserted to be observed.

## Completion and failure policy

All built-in adapters reject empty or unfinished completions, known model
mismatches and invalid token/response-ID telemetry before constructing a review.
Redirects and hidden SDK retries are disabled. Shared `Judge` retries provider
failure once and permits one repair round trip only for unreadable JSON.
Readable invalid opinion schemas or failed finding evidence are unavailable
immediately, without repair. A failed judge contributes an error and no vote.

Timeouts apply to each call, not the whole panel. Native and compatible routes
store endpoint identity as a hash. Direct SDK routes do not distinguish
environment-configured endpoints in their configuration IDs. Configured secrets
are excluded from reviewer IDs and saved parameters.
Built-in adapter errors retain class/HTTP status without raw provider bodies.
Custom `Judge` implementations must enforce their own transport and error
sanitization boundaries. See [security](SECURITY.md).

Different vendors, routes or roles do not prove independent errors. Direct and
OpenRouter-routed models from the same vendor share one provider label. The
intentional single-provider blocking exception is described in [evaluation](EVALUATION.md).
