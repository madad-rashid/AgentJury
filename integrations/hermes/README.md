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

1. Install published AgentJury and the judge SDKs into Hermes's Python:
   `<hermes-python> -m pip install "agentjury[all]>=0.5.0,<0.6"`.
   If the venv was made by `uv`, use
   `uv pip install --python <hermes-python> "agentjury[all]>=0.5.0,<0.6"`.
   When switching an existing Git/editable installation to PyPI, reinstall only
   AgentJury explicitly: `uv pip install --reinstall-package agentjury --python <hermes-python> "agentjury[all]>=0.5.0,<0.6"`,
   or `<hermes-python> -m pip install --force-reinstall --no-deps --index-url https://pypi.org/simple "agentjury==0.5.1"`
   followed by the install command above for SDK/dependency requirements.
   Verify version `0.5.1`, schema `0.7`, import location and provenance using the
   [migration checks](../../docs/MIGRATION.md), then run `<hermes-python> -m pip check`.
   Restart Hermes after replacing a package already loaded by its process.
2. Separately link or copy `integrations/hermes` from the updated `main` checkout
   to `<hermes-home>/plugins/agentjury/`. The core wheel does not install this
   folder; an existing copied plugin is not updated by a core package upgrade.
   (Windows: `mklink /J <hermes-home>\plugins\agentjury <path-to-this-folder>`).
3. Add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_WORKSPACE_ID` if your key needs it,
   to `<hermes-home>/.env`.
4. `hermes plugins doctor <hermes-home>/plugins/agentjury`, then `hermes plugins enable agentjury`.
   Decline the tool-override capability; AgentJury never replaces built-in tools.
5. Start `hermes`, ask something substantial, wait ~20s, type `/jury`.
   Troubleshoot with `hermes logs --level INFO | findstr /i agentjury` (Windows) or `| grep -i agentjury`.

## Configure

This integration requires schema 0.7 and published AgentJury `>=0.5.0,<0.6`;
0.5.1 is the current release. The manifest also installs vendor SDKs for the
default panel. PyPI 0.5.0 and later include the preset safeguard; older PyPI
0.4.4 lacks the matching coverage fields.
Native-only core routes do not themselves require either SDK.
See [migration](../../docs/MIGRATION.md) and [providers](../../docs/PROVIDERS.md)
for compatibility and installation provenance checks.

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
For an OpenRouter-only panel, install published AgentJury into Hermes's Python
environment as above, set `OPENROUTER_API_KEY` in Hermes's `.env`,
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
With core 0.5.1 or later in Hermes's interpreter (0.5.0 lacks the command),
`agentjury adjudication pending --dir <HERMES_HOME>/plugin-data/agentjury/verdicts`
lists what still needs grading there, and `export` shares the grades without
the reviewed text.
