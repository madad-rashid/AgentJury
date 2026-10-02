# AgentJury — unreleased branch changes

These changes integrate the draft provider and free-jury branches locally and
have not been published to PyPI.
The current published v0.4.4 release notes remain a record of that release.

- Added OpenRouter, Ollama, and generic OpenAI-compatible provider routes.
- Added a local benchmark for comparing explicit free-model panels on built-in
  and user-supplied labeled cases. The call cap counts provider attempts,
  including retries and repair requests.
- Added the `source_audit` role for source and as-of-date checks when a task
  explicitly asks for a source.
- Moved the reviewer rubric to 0.5. The `critic` role is skeptical without
  assuming every answer is flawed. Findings require checked excerpts; invalid
  evidence can make a review unavailable. Repair prompts no longer echo the
  malformed reply. Verdicts can therefore change under the new rubric.
- Excerpt matching now tolerates limited whitespace and typography differences.
  It does not verify the truth of a model's interpretation. Model-authored
  free-text reasons are replaced by neutral summaries of accepted reviews.
- Restored support for trailing commas in panel specifications. Empty panels
  still fail.
- Integrated native Ollama and OpenRouter transports with strict response/model
  checks, observed-model telemetry, sanitized failures and no redirects.
- Rejected duplicate reviewer configurations and normalized equivalent endpoint
  identities. Provider labels remain diversity proxies, not independence proofs.
- Added artifact-addressed finding evidence and schema 0.7 coverage/digest fields.
  Hermes no longer certifies omitted, truncated, changed or superseded files,
  excludes prior jury metadata from reviewer input and explains local warnings.
- Made adjudication prevalidated, serialized and recoverable using pending audit
  events, atomic replacements and idempotent event IDs.
- Required correct-case acceptance and zero missed injected blocks for provisional
  benchmark suggestions. Starter examples remain smoke tests, not accuracy proof.
- Added an offline-suite network guard; live model tests remain opt-in.
- Applied completion/model checks, observed-model telemetry and sanitized errors
  to direct OpenAI/Anthropic SDK adapters too. SDK redirects are disabled.
  Development extras include SDKs for realistic offline response-shape tests;
  native transports still have no SDK runtime dependency.
