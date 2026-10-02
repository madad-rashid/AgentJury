# Security and data boundaries

AgentJury reviews caller-supplied material. Its prompt treats task, context,
output and artifacts as untrusted data. Built-in reviewers see the same request
without other reviewers' votes or verdicts; deterministic aggregation runs after
their responses. Prompt delimiters are instructions to a model, not a sandbox or
a proof that prompt injection cannot work.

The deterministic local guard detects selected explicit reviewer commands in
the answer text. It can downgrade approval to `needs_revision`, but does not
cast a vote or create a judge finding. It is not an exhaustive injection scanner
and does not scan task/context/artifact text with those rules. The reviewer prompt
still labels all those sections untrusted. Checked excerpts validate source
provenance, not the truth or safety of the reviewer's interpretation.

## Selected destinations and saved content

The selected judges receive the task, output, configured context and captured
artifact text. Native Ollama defaults to localhost but can be configured remote.
OpenRouter and vendor routes send material to their configured service. Compatible
endpoints may also be remote. There is no automatic privacy-routing policy.
SDK environment configuration can affect direct vendor endpoints; deployers must
control their configuration. API keys are supplied through the environment or
local ignored `.env` file; never include them in submitted artifacts or prompts.

Verdicts persist findings and checked excerpts locally. Sidecars duplicate verdict
content beside eligible files. Benchmark reports omit original case text and
checked excerpts, but model findings can still repeat sensitive content. Review
files before sharing them; a local report is not automatically redacted.

Built-in adapters disable redirects, check completion/model reports, validate
telemetry and sanitize transport exceptions. Model reports and endpoint hashes
are provenance telemetry, not cryptographic attestations. Custom in-process
judges/framework integrations are trusted executable code and are not isolated.
Custom exceptions can be saved by the panel; sanitize them before raising.

## Hermes file annotations

Hermes annotates only complete, unchanged, current-generation snapshots. Up to
five files and 20,000 characters per file are reviewed; partial, omitted or
unavailable coverage is explicit. Current-generation skipped certification is
removed best effort. Newer generations prevent late reviews from touching that
file, including across sessions sharing one Jury instance.

Content digests cover UTF-8 text after newline normalization and removal of
AgentJury frontmatter keys, not exact raw filesystem bytes. The verdict records
artifact identity, digest, request/run identity and coverage; it does not store
a full task-content hash. A matching digest alone
does not establish that the annotation applies to the latest task. Check the run
ID and coverage too. Storage failures are reported as `write_failed`; permissions
can prevent cleanup of an old annotation.

Checks and atomic replacements are serialized inside one plugin instance.
External writers and separate plugin processes do not share the lock, and a
check followed by replacement is not an atomic filesystem compare-and-swap.
Consumers must validate current content and run identity before trusting metadata.

## Human adjudication

All requested references/labels are validated before persistence. A directory
lock serializes writers. Verdict replacement first saves pending audit events;
history publication is idempotent by event ID. An interruption can leave pending
events visible in the verdict, and the next valid adjudication retries publication.
The CLI explicitly reports this state. These are recoverable separate files,
not one multi-file transaction. Preserve pending events and existing JSONL history.

The offline test guard blocks endpoints except ephemeral test-process servers.
`AGENTJURY_LIVE=1` intentionally disables that guard and enables live tests; use
it only for a separately authorized live run. See [evaluation](EVALUATION.md).
