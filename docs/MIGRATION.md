# Migration to the 0.5.0 public alpha

Provider and integrity changes are merged into `main`; version 0.5.0 is being
prepared, not published. PRs 6/7 are closed as superseded by PRs 8/9. Until
publication, the immutable guarded core below provides the matching behavior
while retaining its historical metadata version 0.4.4. It differs from PyPI
0.4.4, which lacks these changes.

```bash
pip install --force-reinstall "agentjury[all] @ git+https://github.com/madad-rashid/AgentJury.git@3023b96cadf7056076beb94e6dbbd9e3395858a8"
```

The reinstall above replaces an existing PyPI 0.4.4; verify
`python -c "import agentjury; print(agentjury.SCHEMA_VERSION)"` prints `0.7`.
Check source provenance too:

```bash
python -c "import importlib.metadata as m, json; print(json.loads(m.distribution('agentjury').read_text('direct_url.json'))['vcs_info']['commit_id'])"
```

It must print `3023b96cadf7056076beb94e6dbbd9e3395858a8` for the pinned
installation. Schema alone does not establish that the preset guard is present.
Use the updated plugin folder from this release-readiness PR or `main` after
merge, not the older plugin manifest at the pinned core commit. From a matching
checkout, `pip install -e ".[all,dev]"` prepares offline development.
Native-only applications may install core without `[all]` and use
Ollama/OpenRouter without SDK runtime dependencies. Development extras include
SDKs for realistic offline response tests. Core requires Python 3.11+.

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

Install a matching guarded core and plugin. The manifest pins core to immutable
commit `3023b96cadf7056076beb94e6dbbd9e3395858a8`, including the restored preset guard.
After confirmed PyPI publication, replace that Git dependency with
`agentjury>=0.5.0,<0.6` in a follow-up and use the same requirement in install
guidance. Do not make that switch while PyPI 0.5.0 is unavailable.
The manifest retains SDK dependencies for its default vendor panel.

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
