# Local integrity fixes and validation

This work integrates draft PRs 5, 6 and 7 on `fix/review-integrity` for a draft
consolidation pull request. It is not merged, released or deployed. Local fix
commit: `f88bc49eb6771ae10ce08f1efc33ccf32faea28c`; subsequent documentation
and any CI fixes are separately visible in the branch history.
The package version remains 0.4.4 for local validation; schema is 0.7 and
reviewer rubric is 0.5. Choose a new unused package version before publication.

## Exact inputs

| Input | Reviewed commit |
| --- | --- |
| main | `4bdad8cdb9ac9831375d02c3cdcf34c56cc0a1ca` |
| PR 5 / local integration base | `97eccbee8eef05004c36238622083279b29b2a4a` |
| PR 6 / native Ollama source | `f30d6f673d0807e8d8410f48bf4b4f029bc857db` |
| PR 7 / native OpenRouter source | `0ee64059691ec10b2363cc17be31dec61ed190db` |

PR 5 supplies grounded findings, source audit, local reviewer warnings and the
benchmark. Native provider transports from PRs 6/7 are integrated through its
shared panel parser. Existing implementation branches and PRs remain open;
cross-reference comments link them to the consolidation without closing or merging.

## Fixed defects

| Problem | Result | Regression coverage |
| --- | --- | --- |
| Hermes certified omitted/truncated files and allowed late annotations to overwrite newer runs | Explicit full/partial/omitted/unavailable coverage, snapshot digests, cross-session generations and serialized annotation checks | `tests/test_artifact_integrity.py` |
| Prior certification survived skipped/failed reviews; first sidecar had incomplete coverage | Current-generation certification invalidation, final-coverage publication, best-effort superseded sidecar cleanup | `tests/test_artifact_integrity.py` |
| File-only defects could not supply accepted evidence | Artifact IDs address primary and basis excerpts, including duplicate filenames | `tests/test_artifact_integrity.py`, `tests/test_finding_evidence.py` |
| Hermes hid local warnings or attributed them to dissenting judges | Separate local-check display and feedback | `tests/test_artifact_integrity.py` |
| Identical configurations and known Ollama aliases cast multiple votes | Duplicate configuration rejection and same-route alias identity normalization | `tests/test_panel_integrity.py` |
| Adapters accepted wrong models or unfinished completions and could leak provider errors/telemetry | Native/direct/compatible shape and model checks, observed model telemetry, no redirects, sanitized error boundaries | `tests/test_direct_judge_integrity.py`, `tests/test_compatible_judge.py`, `tests/test_ollama_judge.py`, `tests/test_openrouter_judge.py` |
| A later invalid adjudication left history inconsistent with the verdict | Complete reference prevalidation, atomic per-file replacement, directory lock, recoverable pending events and idempotent replay | `tests/test_cli_adjudicate.py` |
| Always-revise or unavailable-injection panels could be recommended | Correct-case acceptance threshold and all-injected-blocked gate alongside safety/availability requirements | `tests/test_benchmark_score.py` |
| Native-route test assumptions could permit local inference | Offline socket/DNS guard and corrected SDK fixtures; guard and Hermes files included in source distribution | `tests/conftest.py`, `tests/test_offline_guard.py`, `MANIFEST.in` |

## Validation evidence

Environment: Windows, CPython 3.13.5, task-local virtual environment with
Pydantic 2.13.5, pytest 9.1.1, OpenAI SDK 3.23.0, Anthropic SDK 1.11.0,
setuptools 84.0.0 and wheel 0.48.0. Dependencies came from official PyPI.

- PR 5 baseline: **263 passed, 2 skipped**.
- Final complete checkout suite: **386 passed, 2 skipped**, 56.29 seconds.
- Built source distribution suite: **386 passed, 2 skipped**, 54.36 seconds.
- Source and wheel builds: passed with `python -m build --no-isolation`.
- `python -m twine check`: passed for both distributions.
- Wheel/source content checks: native adapters, starter dataset, SPDX license,
  CLI entry point, offline guard and Hermes source present as appropriate.
- Installed wheel bytes matched the built wheel; schema 0.7, fake-panel review,
  CLI roles and benchmark help smoke checks passed outside the source tree.
- `git diff --check`: passed.
- Independent whole-branch review: five further confirmed edge cases fixed;
  no significant review blockers remained. Its focused passing runs overlap
  the full suite and are not additional independent samples.
- Independent two-process Windows adjudication lock probe: competing writer
  blocked while locked, then acquired after release.

All final offline regression tests set `AGENTJURY_LIVE=0` and blocked non-test network endpoints.
Native HTTP tests used ephemeral local mock servers; direct/compatible tests
used credential-free stubs or dummy keys and realistic SDK response classes.
At that offline-validation stage, no authorized live inference validation had
been performed; the separately authorized local smoke is recorded below.
An earlier combined run was interrupted after an obsolete missing-SDK fixture could reach the
native local HTTP route; no completed model inference was established. The
fixture was corrected and the network guard added before further full runs.

Failures were reproduced before fixes: artifact regression 10 failures;
adjudication/recommendation regression 9 failures; direct SDK regression 14
failures; adapter and independent-review regressions separately reproduced
their target failures. The final suite is the authoritative combined result.

## Process assessment and remaining limits

The core process remains blind concurrent review followed by deterministic
aggregation. Requested-panel strict-majority quorum, abstention treatment,
provider floor and the intentional single-provider blocking exception remain
unchanged. Different model authors/providers are diversity proxies, not proof
that errors are independent. Confidence is not calibrated, and `verified`
describes this jury's approval rather than truth or safety certification.

Checked excerpts establish provenance, not correctness of the interpretation.
Source audit checks named source/date traceability without fetching sources.
The starter benchmark is a smoke test, not empirical general-accuracy evidence.
No new live accuracy or false-finding-rate claims follow from these unit tests.

Hermes locks coordinate one Jury instance. External writers and separate
processes can still race filesystem checks; digests, run IDs and coverage must
be checked together. Storage permissions can prevent old-metadata cleanup;
failures are surfaced rather than reported as successful certification.
Adjudication uses recoverable separate files, not one multi-file transaction.

Hard whole-panel deadlines, task-lineage feedback, privacy routing and measured
correlation/reputation/confidence calibration remain separate design work.
Linux and other Python versions were not rerun locally; the draft pull request's
configured CI matrix supplies those checks. Their exact outcome belongs to that
revision's GitHub checks rather than these historical local test counts.
Publication of a draft PR was separately authorized after the local fix commit.
Merging and release/deployment remain separately authorized actions. Publishing
this branch itself does not provide live-model validation; the later local smoke
was separately authorized and is described below.


## Authorized local Ollama smoke — 2026-10-02

Synthetic live cases were run against exact published implementation commit
`bc0c217050a2d2c1a0a1654278a4572ee805331f`, after verifying local and remote
branch heads matched. This documentation follow-up changes no implementation.
Ollama was already running on loopback. Its installed inventory contained only
`qwen3:4b-instruct` (4B, Q4_K_M) and `qwen3:0.6b`; no larger installed model was
available for comparison. Nothing was downloaded or installed.

The smoke used `qwen3:4b-instruct`, whose installed digest was
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
Accuracy and critic roles used the same model/provider, quorum 2, and sequential
execution. A task-local harness injected native payload options: temperature 0,
seed 42, context 8,192, output limit 1,200 tokens, thinking disabled, and
`keep_alive=2m`. Each native HTTP call had a 90-second timeout, transport retries
were disabled, and each judge could make its existing single opinion-repair
attempt. These are bounded harness overrides, not stock CLI defaults. The
native adapter, parsing, evidence validation, repair and aggregation code were
unchanged. Successful and diagnostic responses reported the requested model.

| Synthetic case | Expected useful review | Actual result | Wall time |
| --- | --- | --- | --- |
| Correct answer: `17 + 25 = 42.` | Approvals without findings | `verified`, 2 approve / 0 revise, score 10, heuristic confidence 0.5; no findings or errors | 3.84 s |
| Wrong answer: `17 + 25 = 43.`, with reference answer 42 in context | Grounded blocking findings | `insufficient_jury`; neither role produced a valid opinion, including repair; both failed JSON/evidence validation | 26.42 s |
| Correct disposable Markdown arithmetic note through Hermes hooks | Approve the artifact and record coverage | `insufficient_jury`; neither role produced a valid opinion, including repair; both failed validation | 33.29 s |

Additional instrumented accuracy-role reproductions captured the reason for
rejection. For the wrong answer (10.85 s), the model correctly recognized 43
instead of 42, but added a second finding whose output excerpt quoted the
reference answer 42, absent from the agent output. Repair repeated this invalid
attribution. For the correct file (12.64 s), it produced contradictory criticism
claiming the equation was both wrong and correct, alongside invalid output
excerpts/artifact attribution; repair remained invalid. These additional
reproductions are distinct from the primary cases. The evidence gate correctly
rejected the opinions. Raw proposed findings are not accepted verdict findings,
and rejection is not evidence that the model correctly assessed every case.

The Hermes case exercised actual plugin registration and the `post_tool_call`,
`post_llm_call` and `pre_llm_call` handlers with an isolated fake host context,
real local inference and disposable storage. The harness created the file and
signaled the write-tool hook; a running Hermes producer did not perform that
write. Full artifact coverage and applied annotation were recorded, with
`insufficient_jury` frontmatter, sidecar and persisted verdict. Feedback was
returned once, then absent on the next call. This is integration-harness
coverage, not full installed/running-Hermes end-to-end validation. No real vault,
Discord, gateway credentials or production configuration was accessed.

A separate refused-loopback endpoint probe returned `insufficient_jury` and a
sanitized `URLError` in 2.01 s, with no model inference. The completed smoke had
no timeout or token-truncation failures. An initial harness run was interrupted
after identifying an incorrect harness factory attribute; the harness was
corrected outside the repository and all three reported cases rerun. The
correct case took 8.74 s initially and 3.84 s in the final warm-model run; the
table reports the final complete run.

The configured all-Ollama panel can return `verified`: the provider floor is
`min(2, requested_providers)`, so a configured single-provider panel has floor 1.
A mixed-provider panel degraded to one provider remains insufficient. The two
local roles do not establish independent judgment. A policy requiring local-only
approval to remain advisory would be a separate behavior change.

Conclusion: native local transport and fail-closed opinion validation worked,
but this 4B model was unreliable on these three simple cases. Do not weaken
provenance checks to obtain a verdict. Before routine certification, evaluate
model/prompt compliance on a representative labeled pack, including correct
artifact acceptance and grounded wrong-answer rejection. This tiny smoke proves
neither general accuracy nor reviewer independence. There were no cloud model
calls, credentials, production changes, merges or releases.


## Authorized larger local comparison — 2026-10-02

After separate hardware-check/download authorization, the same three synthetic
cases ran once on exact PR head `e1f60186359bb3f4cd2e5397d3f6a1ed021ea9a8`.
That head only added the preceding smoke documentation to implementation
`bc0c217`; the working tree was clean before and after inference.

Hardware observed: RTX 4070 Laptop GPU, 8,188 MiB VRAM; 31.4 GiB physical RAM,
about 9.5 GiB available at selection; 17.2 GiB free disk before download.
The [official Ollama registry](https://ollama.com/library/qwen2.5:7b-instruct)
listed `qwen2.5:7b-instruct`, 7.62B parameters, Q4_K_M, approximately 4.7 GB,
under Apache 2.0. One model was downloaded through existing Ollama, which
verified its SHA-256 before success. Installed digest:
`845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`.
The installed size was 4,683,087,332 bytes, leaving 12.8 GiB free disk. Both
previous Qwen models were preserved; no software or system settings changed.

The task-local harness retained temperature 0, seed 42, context 8,192,
output limit 1,200 tokens, 90-second per-call timeout, zero transport retries,
single opinion repair, sequential accuracy/critic roles and quorum 2. This
model has no thinking capability, so the unsupported `think` payload field
was omitted rather than sent as false. Other case contents and native
protocol/evidence/aggregation behavior were unchanged. Raw native responses
were captured for these synthetic cases. There were eight completed calls:
two per arithmetic case and four for the artifact case including repairs.
All reported the requested model and `done_reason=stop`; no timeout or
truncation occurred. No additional live diagnostic inference was needed.

| Same synthetic case | Prior 4B result / time | 7B result / time |
| --- | --- | --- |
| Correct `17 + 25 = 42.` | `verified`, 2 approve / 3.84 s | `verified`, 2 approve, no findings, score 10 / 26.33 s |
| Wrong `17 + 25 = 43.` | `insufficient_jury`, invalid opinions / 26.42 s | `needs_revision`, 2 revise with accepted major findings / 7.37 s |
| Correct disposable file through Hermes hooks | `insufficient_jury`, invalid opinions / 33.29 s | `insufficient_jury`, both opinions invalid after repair / 15.77 s |

Both 7B wrong-answer findings correctly pointed to `17 + 25 = 43.` and quoted
the task as their basis. Both labeled it `major`, not `blocking`, so the
expected wrong-answer rejection occurred but the hoped-for blocking verdict
did not. Accepted excerpts prove attribution, not the arithmetic inference.

For the correct file, both roles falsely criticized `17 + 25 = 42.`. Their
basis excerpts claimed that equation appeared in the assistant response, which
only said the note had been written. The artifact quote was present, but its
basis source was wrong. Repair retained invalid attribution; one repair also
omitted the artifact ID. Strict evidence validation correctly rejected these
opinions. No valid findings entered the aggregate, and the model's false
criticism remains an observed quality failure rather than a proven file defect.

The actual isolated Hermes registration/hooks again persisted the verdict,
recorded full artifact coverage with applied annotation, wrote
`insufficient_jury` frontmatter/sidecar, and returned feedback once, then none.
This remains host integration-harness validation, not running-Hermes producer
or production-vault end-to-end validation.

Ollama reported 4,987,132,312 bytes of model VRAM at context 8,192, with
`size_vram` equal to its runtime model size. A GPU snapshot showed 6,861 MiB
used overall and 1,088 MiB free while inference ran. The first correct-case
call took 24.42 s, including 12.55 s model loading and 10.48 s prompt evaluation;
the second took 1.87 s. This cold run is not a like-for-like latency comparison
with the prior warm 4B result. Other reported times include any repair calls.
No memory-pressure failure was observed; only the bounded context was tested.

The larger model improved usable wrong-answer review in this tiny comparison,
but still failed correct artifact acceptance and severity expectations. Model
family/version, template and thinking support also changed, so improvement
cannot be attributed solely to parameter count. Both roles use the same local
model/provider; neither statistical independence nor calibrated confidence is
established. No automatic benchmark recommendation was run or earned.

Recommendation: retain the evidence gates and keep this configuration in
experimental use. Next evaluate correct-artifact acceptance, excerpt-source
compliance and severity consistency on a representative labeled pack before
routine certification. Do not infer that downloading a larger model solved
review quality. No cloud inference, credential handling, production gateway
changes, existing-model deletion, merge or release occurred.


## Artifact-prompt investigation — 2026-10-02

The authorized targeted diagnosis used baseline PR head
`ac780dfea5ac0d8651697878a8858d7c8004d130` and installed
`qwen2.5:7b-instruct`. No production code, rubric, prompt or evidence-validator
change was retained. A throwaway task-local harness compared the exact existing
prompt with one general candidate: explicitly review response plus artifact
deliverables; distinguish response and artifact excerpt sources; describe both
sources in the JSON example; remind repair to recheck defects and attribution.
The candidate was not tailored to a particular calculation or file name.

The previously captured failures showed two separate problems: false criticism
of a correct equation, and quoting artifact content as if it appeared in the
assistant's short file-writing response. Existing prompt wording emphasizes
AGENT OUTPUT at the final instruction and JSON example despite earlier artifact
allowance. This is a plausible ambiguity, not proof of the causal explanation.
The evidence validator was working as designed; literal-source validity cannot
establish that a criticism is true.

Before inference, eight synthetic cases, splits and expected votes were declared:
four development cases (correct/wrong arithmetic, correct/wrong checklist),
then four held-out cases (correct/wrong JSON, correct/wrong pairs of artifacts
sharing a filename but having distinct IDs). Development used accuracy;
held-out used accuracy and critic. Correct cases expected approval with no
findings; defective cases expected a grounded revision identifying the actual
artifact defect. There were 12 review opportunities per variant. The same
90-second timeout, zero transport retries, one opinion repair, 1,200-token cap,
8,192 context, temperature 0 and seed 42 were used. Native inference made
**36 calls**, including repairs, within the predeclared 48-call ceiling.
All reported the requested model and normal stop, with no timeout/truncation.

The one candidate was frozen before inspecting held-out outputs; no tuning or
second candidate followed those outputs. All recorded system/user/repair prompts
were checked against the same unchanged runner and matched exactly. The runner
rewrote the same freeze file between stages and did not enforce an immutable
baseline/hash at runtime; this is a methodology limitation, not a claim of a
hardened evaluation runner. Synthetic cases, exact prompt templates, parameters,
raw responses and parsed results are in
[the investigation evidence](artifact-prompt-investigation.md).

| Case / expected vote | Baseline accepted votes | Candidate accepted votes |
| --- | --- | --- |
| Development arithmetic correct / approve | accuracy: unavailable | accuracy: revise, false finding |
| Development arithmetic wrong / revise | accuracy: revise | accuracy: unavailable |
| Development checklist correct / approve | accuracy: revise, false finding | accuracy: approve |
| Development checklist wrong / revise | accuracy: revise, wrong rationale | accuracy: unavailable |
| Held-out JSON correct / approve | accuracy: approve; critic: approve | accuracy: approve; critic: approve |
| Held-out JSON wrong / revise | accuracy: unavailable; critic: revise, mixed true/false findings | accuracy: unavailable; critic: unavailable |
| Held-out duplicate filenames correct / approve | accuracy: approve; critic: approve | accuracy: approve; critic: approve |
| Held-out duplicate filenames wrong / revise | accuracy: unavailable; critic: unavailable | accuracy: unavailable; critic: unavailable |

| Metric | Baseline | Candidate |
| --- | --- | --- |
| Protocol/evidence-valid reviews | 8/12 | 6/12 |
| Accepted votes matching expected label | 7/12 | 5/12 |
| Correct-artifact approval | 4/6 | 5/6 |
| Defective-artifact accepted revision | 3/6 | 0/6 |
| Defective-artifact approval | 0/6 | 0/6 |

The expected-vote metric is not review correctness. Baseline's checklist-wrong
review chose revision for the wrong reason: it demanded the checklist in the
assistant response, despite a supplied artifact, rather than identifying Delete
instead of Publish. The baseline JSON-wrong critic identified pending instead
of ready correctly, but also falsely demanded JSON in the assistant response.
The candidate arithmetic-correct review was accepted after repair because its
artifact/task quotes existed, yet falsely labeled the matching equation a defect.
These are substantive model errors even when evidence provenance is valid.

Independent read-only review recomputed all counts, verified the recorded
prompt variants and revalidated accepted evidence. It confirmed the source
distinction is defensible,
but ambiguity is not established as the root cause. It also noted that the
candidate's broad approval instruction could interfere with role-specific
abstention or response defects; this is another reason not to adopt it. The
experiment did not cover injection resistance, partial artifact coverage,
conflicting response claims, production Hermes or general reliability. Baseline
always ran first; no comparative latency conclusion is drawn. The candidate
changed multiple wording instructions together, so effects cannot be attributed
to one sentence.

Decision: **discard the candidate**. Its gain on one correct checklist did not
offset reduced availability and loss of accepted defective-artifact revisions.
No defensible prompt improvement was demonstrated, and evidence gates remain
unchanged. No implementation was made, so no new regression tests or claimed
TDD fix result accompanies this docs-only negative finding. Next decide whether
to fund a separate controlled experiment with structured source-addressed input
and targeted safe validation-error feedback, using a fresh held-out set; do not
weaken quote checks or accept the present model for routine certification.
No new downloads, cloud inference, credentials, production changes, merge or
release occurred during this investigation.
