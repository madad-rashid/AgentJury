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

All final tests set `AGENTJURY_LIVE=0` and blocked non-test network endpoints.
Native HTTP tests used ephemeral local mock servers; direct/compatible tests
used credential-free stubs or dummy keys and realistic SDK response classes.
No authorized live inference validation was performed. An earlier combined
run was interrupted after an obsolete missing-SDK fixture could reach the
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
Merging, release/deployment and live-model validation remain separately authorized
actions. No new live-model validation follows from publishing this branch.
