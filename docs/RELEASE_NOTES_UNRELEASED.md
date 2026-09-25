# AgentJury — unreleased branch changes

These changes are on `phase-two-free-jury` and have not been published to PyPI.
The current published v0.4.4 release notes remain a record of that release.

- Added OpenRouter, Ollama, and generic OpenAI-compatible provider routes.
- Added a local benchmark for comparing explicit free-model panels on built-in
  and user-supplied labeled cases. The call cap counts provider attempts,
  including retries and repair requests.
- Added the `source_audit` role for source and as-of-date checks when a task
  explicitly asks for a source.
- Moved the reviewer rubric to 0.4. The `critic` role is skeptical without
  assuming every answer is flawed. Findings require checked excerpts; invalid
  evidence can make a review unavailable. Repair prompts no longer echo the
  malformed reply. Verdicts can therefore change under the new rubric.
- Excerpt matching now tolerates limited whitespace and typography differences.
  It does not verify the truth of a model's interpretation. Model-authored
  free-text reasons are replaced by neutral summaries of accepted reviews.
- Restored support for trailing commas in panel specifications. Empty panels
  still fail.
