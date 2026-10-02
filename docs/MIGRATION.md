# Draft consolidation migration

This guide applies to `fix/review-integrity`, combining PR 5's free-jury process
with PRs 6/7's native transports and integrity fixes. It is a draft, not a PyPI
release. Existing implementation PRs remain open for comparison.

```bash
pip install "agentjury[all] @ git+https://github.com/madad-rashid/AgentJury.git@fix/review-integrity"
```

From a matching checkout, `pip install -e ".[all,dev]"` prepares offline
development. Native-only applications may install core without `[all]` and use
Ollama/OpenRouter without SDK runtime dependencies. Development extras include
SDKs for realistic offline response tests. Core requires Python 3.11+.

## Configuration changes

| Earlier configuration | Draft behavior / action |
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
0.6. All configuration IDs include that policy version, including plain-text
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

Install core and plugin from the same branch. The draft manifest pins its core
dependency to this branch because older released cores lack coverage fields.
After an actual release, replace that direct Git reference with the new version.
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
