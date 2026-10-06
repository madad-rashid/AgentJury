# AgentJury v0.5.0 - published release and repository follow-up

Version 0.5.0 was published to PyPI on 2026-10-03 from commit
`8aa02e1c5e9dc96149c1b99a5dc66e96d5a6770b`. The
[GitHub release](https://github.com/madad-rashid/AgentJury/releases/tag/v0.5.0)
and its artifacts remain unchanged, as do the historical v0.4.4 release notes.

Repository follow-up: Hermes now requires `agentjury>=0.5.0,<0.6` instead of
the temporary guarded Git pin. Install guidance describes explicit core
reinstallation/provenance checks and separate plugin-folder installation.
These documentation/manifest changes do not update an installed Hermes environment
or the immutable PyPI README/sdist snapshot, and do not constitute another release.

The 0.5.0 release included:

- Restore fixed-model validation for native and SDK OpenRouter routes, including
  direct SDK judge construction. Reject preset references before transport
  creation while preserving fixed model slugs and colon variants. Other provider
  model policies remain unchanged.

- Recompute full-artifact digests and revalidate a detached request at panel
  dispatch, preventing supplied or stale hashes from identifying different
  content in verified coverage. Preserve partial-artifact full-source hashes.
- Replace the provider-access plan's machine-specific interpreter path with
  portable Python environment commands.

- Added OpenRouter, Ollama, and generic OpenAI-compatible provider routes.
- Added a local benchmark for comparing explicit free-model panels on built-in
  and user-supplied labeled cases. The call cap counts provider attempts,
  including retries and repair requests.
- Added the `source_audit` role for source and as-of-date checks when a task
  explicitly asks for a source.
- Updated the reviewer rubric through 0.5/0.6 to current policy 0.7. The `critic` role is skeptical without
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
- Added provider, security, evaluation and schema/configuration migration guides,
  aligned Hermes dependencies with an immutable guarded core pin,
  and corrected the demonstration's blocking/severity semantics.

- Artifact-bearing requests now present explicit JSON source IDs and coverage;
  reviewer-rule evidence remains available. Plain-text-only prompt format is
  unchanged. Rubric/input policy 0.6 versions all reviewer configuration IDs.
- A small frozen local ablation favored source presentation, not targeted repair;
  original-file and security failures remain. See the validation report before
  treating this alpha as a production reviewer.

- Review policy 0.7 permits one retry only for unreadable JSON. Readable invalid
  opinion schemas or failed evidence produce an unavailable judge without
  trusting invalid findings or allowing a second opinion to erase them.
- Recorded injection-to-approval repair regression is covered offline. Fresh
  local probes still show direct injected-artifact approval and false revision
  of an inert quotation; this is not general prompt-injection resistance.
