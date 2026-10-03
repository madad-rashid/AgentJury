# Migration to the 0.5.0 public alpha

Version 0.5.0 is published on [PyPI](https://pypi.org/project/agentjury/0.5.0/).
It includes schema/review policy 0.7 and the restored preset safeguard. The old
temporary Git pin `3023b96cadf7056076beb94e6dbbd9e3395858a8` reported historical
version 0.4.4; the older PyPI 0.4.4 package lacks these changes.

## Install or switch to PyPI

For a fresh environment, install:

```bash
python -m pip install "agentjury[all]>=0.5.0,<0.6"
```

An existing Git/editable package reporting 0.5.0 can already satisfy this
requirement without being replaced. To switch explicitly to the released wheel,
reinstall only AgentJury, then ensure dependencies and SDKs are present:

```bash
python -m pip install --force-reinstall --no-deps --index-url https://pypi.org/simple "agentjury==0.5.0"
python -m pip install "agentjury[all]>=0.5.0,<0.6"
python -m pip check
```

With `uv`, use `uv pip install --reinstall-package agentjury --python <target-python> "agentjury[all]>=0.5.0,<0.6"`.
For Hermes, `<target-python>` is Hermes's interpreter, not an unrelated system
Python. Restart Hermes after upgrading an already-loaded package.

Verify with that same interpreter:

```bash
python -c "import agentjury, importlib.metadata as m; print(m.version('agentjury'), agentjury.__version__, agentjury.SCHEMA_VERSION); print(agentjury.__file__); print(m.distribution('agentjury').read_text('direct_url.json'))"
```

For the exact 0.5.0 reinstall, expect `0.5.0 0.5.0 0.7`, an import path inside
the intended environment, and `None` for `direct_url.json`. Index-installed
packages normally have no direct URL metadata; VCS/editable installs record their
source there. Absence alone does not authenticate a package: use the explicit
PyPI index above, and check the import path for checkout shadowing.

The Hermes plugin folder is installed separately from the core wheel. Copy or
link `integrations/hermes` from updated `main` into Hermes's plugin directory;
reinstalling core does not refresh an older copied plugin. See the
[Hermes install guide](../integrations/hermes/README.md).
From a matching checkout, `pip install -e ".[all,dev]"` prepares offline
development, not a PyPI provenance check. Native-only applications can omit
`[all]`; Ollama/OpenRouter need no SDK runtime dependencies. Core requires
Python 3.11+.

## Configuration changes

| Earlier configuration | New behavior / action |
| --- | --- |
| `role:openai` / `role:anthropic` | Preserved; explicit model forms also work |
| PR 5 SDK OpenRouter/Ollama routes | Public factories select native transports; old reports remain readable but configuration IDs change |
| `role:ollama` / `role:openrouter` | Set `AGENTJURY_OLLAMA_MODEL` / `AGENTJURY_OPENROUTER_MODEL`, or supply the model explicitly |
| `AGENTJURY_OLLAMA_BASE_URL=.../v1` | Still accepted; native root strips `/v1`. `AGENTJURY_OLLAMA_URL` takes precedence |
| Duplicate reviewers / `foo` plus `foo:latest` in one Ollama route | Remove duplicate configuration; it no longer casts another vote |
| Generic compatible service | Keep explicit model/base URL; upgrade the OpenAI SDK if older than 1.55.3 |
| Direct Anthropic adapter | Use SDK >=1.11.0 for the configured request API |

Redirected, unfinished, wrong-model and malformed-telemetry responses now fail
closed rather than casting votes. Expect more unavailable results from endpoints
that do not satisfy the response contract. See [providers](PROVIDERS.md).

## Protocol and saved data

Schema 0.7 adds artifact IDs/digests/full-or-partial coverage, verdict coverage,
observed model telemetry and pending adjudication events. Old verdicts and old
finding evidence load with default fields. The initial integrity rubric was 0.5; artifact source presentation uses policy
0.6; syntax-only repair uses policy 0.7. All configuration IDs include that
policy version, including plain-text
reviewers. Preserve historical identities and start new benchmark runs. Artifact
requests use structured JSON sources; plain-text-only prompt format is unchanged.

Artifact findings may set `output_artifact_id`, or `basis_source: "artifact"`
with `basis_artifact_id`. Other basis sources omit that ID. See the
[artifact request example](../examples/artifact_request.json). Existing output
excerpts without artifact IDs retain their original semantics.

Do not mix benchmark jobs from older configuration identities. Resume validates
the case pack/panels; a changed identity needs a new run. Preserve old reports as
historical evidence. Recommendations now require correct-case acceptance and
every injected case blocked; earlier suggestions may no longer qualify.

## Hermes and human grading

Install published core `agentjury>=0.5.0,<0.6` and the updated plugin folder
separately. The manifest retains SDK dependencies for its default vendor panel.
Use the installation and provenance checks above when replacing Git or editable
installations; version/schema alone do not prove an environment switched to PyPI.

Partial/omitted/changed/superseded files receive no new certification. Current
generation skipped annotations are invalidated best effort. Read coverage,
run/request identity and normalized content digest together; older metadata
alone cannot establish a current approval. External writers and separate plugin
processes are outside its lock. Feedback is offered once on the next session
turn and does not infer task lineage; disable it for unrelated mixed tasks.

Adjudication validates all references, serializes writers and persists recoverable
pending events before updating history. If publication fails, retain the verdict
and JSONL log and retry a valid adjudication after fixing storage. Event IDs avoid
duplicate history. Do not manually delete pending events. See [security](SECURITY.md).


Readable JSON opinions that fail schema or evidence validation now become
unavailable without a second model opinion. Only unreadable JSON retains a
single retry. Existing evidence/quorum rules are unchanged. Start new benchmark
runs with the new identities; an old run cannot silently resume under policy 0.7.

## Unreleased on `main`: code-change review

`agentjury change` (candidates, prepare, send, status) and the Claude Code
plugin in `integrations/claude-code/` are additions on `main`; the published
0.5.0 package does not contain them. No schema, rubric, aggregation or
existing command behavior changes. Change-review verdicts are schema 0.7
verdicts whose existing `artifact_coverage` lists each selected path with its
working-tree SHA-256 and `full` or `omitted` coverage. Snapshot records live in
`.agentjury/changes/`, outside the verdict directory, so `agentjury verdicts`
and `agentjury adjudicate` work unchanged. The new commands exit 6 for a
refusal and `status` exits 7 for a stale review. `agentjury --version` prints the
package and schema versions. The packaged `correctness`, `security` and `tests`
roles are new reviewer configurations; do not merge their history with other
roles.
