# AgentJury for Hermes

Eligible substantial Hermes responses are submitted to a blind panel of
AI judges. Verdicts are saved, written into the frontmatter of eligible markdown
snapshots Hermes produced that turn, and, if revision is needed, fed
back to Hermes at the start of the next turn.

```
---
agentjury_status: needs_revision
agentjury_votes: "▲1 ▼2"
agentjury_score: 6.3
agentjury_confidence: 0.42
agentjury_request_id: 9a9a900dc86b
agentjury_run_id: 4c1e77a0b2d9
---
```

## Install

Hermes has its own Python environment and its own home directory. Find both first:
`where hermes` (Windows) or `which hermes` shows the launcher; the venv is next to it.
The home directory is the one containing Hermes's `config.yaml` and `.env`
(on Windows often `%LOCALAPPDATA%\hermes`, on Linux/macOS usually `~/.hermes`).

1. Install AgentJury and the judge SDKs into Hermes's Python. If the venv was made by `uv`:
   `uv pip install --reinstall-package agentjury --python <hermes-venv>/Scripts/python.exe "agentjury[all] @ git+https://github.com/madad-rashid/AgentJury.git@3023b96cadf7056076beb94e6dbbd9e3395858a8"`
   otherwise `<hermes-python> -m pip install --force-reinstall ...` with the same packages.
   Reinstall explicitly: both the source pin and old PyPI build report 0.4.4.
   Verify `<hermes-python> -c "import agentjury; print(agentjury.SCHEMA_VERSION)"` prints `0.7`.
2. Link or copy the updated plugin folder from this release-readiness PR (or
   `main` after merge), not the older plugin folder at the pinned core commit,
   to `<hermes-home>/plugins/agentjury/`
   (Windows: `mklink /J <hermes-home>\plugins\agentjury <path-to-this-folder>`).
3. Add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_WORKSPACE_ID` if your key needs it,
   to `<hermes-home>/.env`.
4. `hermes plugins doctor <hermes-home>/plugins/agentjury`, then `hermes plugins enable agentjury`.
   Decline the tool-override capability; AgentJury never replaces built-in tools.
5. Start `hermes`, ask something substantial, wait ~20s, type `/jury`.
   Troubleshoot with `hermes logs --level INFO | findstr /i agentjury` (Windows) or `| grep -i agentjury`.

## Configure

This integration requires the matching schema 0.7 core; the older PyPI 0.4.4
package lacks its coverage fields. The manifest pins immutable guarded commit
`3023b96cadf7056076beb94e6dbbd9e3395858a8` and installs vendor SDKs for the
default panel. That source pin still reports historical version 0.4.4 but
includes the restored preset guard. After confirmed PyPI 0.5.0 publication,
replace the Git dependency with `agentjury>=0.5.0,<0.6` and update install guidance.
Version 0.5.0 has not been published yet. Native-only core routes
do not themselves require either SDK. See [migration](../../docs/MIGRATION.md)
and [providers](../../docs/PROVIDERS.md) for defaults and compatibility.

In `<hermes-home>/config.yaml`:

```yaml
plugins:
  entries:
    agentjury:
      settings:
        panel: "accuracy:openai,domain_expert:anthropic,critic:anthropic,executive:openai"
        roles_file: "/path/to/roles.json"       # defines domain_expert
        context_file: "/path/to/madad-context.md"
        task_type: "research"
        domain: "private_credit"
        min_chars: 400
        frontmatter: true
        sidecar: true
        feedback: true
```

The `panel` setting also accepts explicit `role:provider:model` entries.
For an OpenRouter-only panel, install the current AgentJury repository checkout
into Hermes's Python environment, set `OPENROUTER_API_KEY` in Hermes's `.env`,
and use:

```yaml
panel: "accuracy:openrouter:openai/gpt-4o,critic:openrouter:anthropic/claude-sonnet-4"
```

For a local Ollama server with `qwen3:8b` installed, use:

```yaml
panel: "accuracy:ollama:qwen3:8b,critic:ollama:qwen3:8b"
```

Ollama defaults to `http://127.0.0.1:11434`; set
`AGENTJURY_OLLAMA_URL` in Hermes's environment to change it. The legacy
`AGENTJURY_OLLAMA_BASE_URL` is accepted, including a trailing `/v1`. For another
OpenAI-compatible endpoint, set `AGENTJURY_COMPATIBLE_BASE_URL`, optionally
set `AGENTJURY_COMPATIBLE_API_KEY`, and use `accuracy:compatible:local-model`.
OpenRouter and custom endpoints receive the task and agent output. The model
vendor in an OpenRouter slug determines provider diversity. Ollama judges
share one provider identity, and custom-endpoint judges share another. If the
custom endpoint URL matches the configured Ollama URL, both routes count as
Ollama.

## Artifact coverage

Each turn captures at most five files and at most 20,000 characters from each.
Verdict `artifact_coverage` records full, partial, omitted and unavailable files
separately. Partial and omitted files receive no new certification metadata or
sidecar, and prior certification is removed for the current generation. A full
file is annotated only while its captured generation and content
digest still match. Newer writes in any session using this Jury instance prevent
older reviews from overwriting that file's metadata, even if the body is identical.
Historical verdicts are retained with `changed` or `stale` annotation status.

The SHA-256 scope is UTF-8 text after newline normalization and removal of this
plugin's AgentJury frontmatter keys. Other frontmatter is preserved. The digest
is stored as `agentjury_content_sha256`; sidecar coverage links it to the artifact
ID and run. Earlier jury metadata is removed from the next review's input.
Certification concerns this snapshot and the whole turn's submitted task/output,
not a guarantee about later file contents or an individually graded file.

Annotation checks and atomic replacements are serialized inside one Jury
instance. External writers and separate plugin processes do not participate in
its lock; content is rechecked immediately before replacement, but there is no
filesystem compare-and-swap transaction. Consumers must compare the stored
digest with current normalized content before trusting a historical annotation.
An existing annotation whose digest no longer matches is stale, even if its
status still reads `verified`.
Storage errors can prevent cleanup of an old annotation; they are logged and
recorded as `write_failed` in coverage. Always check the run ID, coverage and
current digest together. All sidecars from a successful turn include the final
coverage results for every captured path.

`/jury` and next-turn feedback display deterministic `Local check` warnings
separately from judge findings. Feedback is offered once on the next session
turn; it does not infer task lineage. Disable `feedback` if that is unsuitable
for sessions that mix unrelated tasks.

## Use

Type `/jury` in any session to see the latest verdict, or `/jury <request_id>`
for a saved one. Verdict JSON accumulates in `<HERMES_HOME>/plugin-data/agentjury/verdicts/`.
