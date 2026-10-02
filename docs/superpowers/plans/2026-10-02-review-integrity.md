# Review integrity implementation plan

The user authorized all confirmed review fixes and local integration of draft
PRs 5, 6 and 7. Existing branches and PRs stay unchanged; no push, release,
deployment, paid inference, credentials or system-wide setup is authorized.

## Design and constraints

Keep the requested-panel strict-majority quorum, abstention behavior, provider
floor, deterministic vote aggregation and intentional single-provider blocking
exception. Source audit remains a traceability reviewer without browsing.
Hard wall-clock deadlines, privacy routing and task-lineage feedback stay deferred.

Use PR5 as the local integration base because it contains the benchmark,
grounded findings and local signals. Integrate PR6 native Ollama and PR7 native
OpenRouter through PR5's shared parser. Preserve explicit models and legacy
short forms with their environment defaults. Keep compatible endpoints as an
optional SDK route. All adapter routes must validate completion shape and known
model identity, sanitize failures, and capture non-secret provenance.

Hermes certification describes a reviewed content snapshot, not every written
file. Capture full SHA-256 digests, full/partial coverage, and stable artifact
identities. Never annotate omitted, truncated, changed, or stale artifacts as
verified. Serialize annotation checks/writes inside this plugin, preserve saved
historical verdicts, and suppress metadata feedback from earlier annotations.
External concurrent writers are outside an atomic filesystem transaction; make
the digest scope explicit and recheck content immediately before replacement.

## Task 1: environment and baseline

Create an isolated local worktree and task-local virtual environment using
official PyPI dependencies. Run `python -m pytest tests -q` with
`AGENTJURY_LIVE=0`. Expected: the PR5 baseline passes with two live tests skipped.
Record remote hashes and test evidence in the progress ledger.

## Task 2: adapters and reviewer identities

Files: judges/ollama.py, judges/openrouter.py, judges/compatible.py,
judges/__init__.py, panel_config.py, panel.py and adapter/panel tests.
Add failing tests for duplicate configurations, wrong returned models,
unfinished completions, normalized endpoint identity, native provider routes,
legacy specs and mixed direct/routed provider counting. Integrate PR6/7 adapter
files and tests, then fix the failures. No actual inference is needed.
Expected: all offline adapter and panel tests pass; full suite green.

## Task 3: artifact evidence and certification

Files: protocol.py, judges/evidence.py, judges/base.py,
integrations/hermes/jury.py and their tests.
Extend evidence with optional artifact IDs for primary and basis quotes while
preserving old saved findings. Add test-first cases for a file-only defect,
sixth artifact omission, truncated coverage, file modification during review,
out-of-order reviews touching one file, and local-signal display/feedback.
Add coverage records to verdicts. Annotate only complete unchanged snapshots;
use content digests and serialized per-file generation checks.
Expected: artifact evidence and certification regression tests pass; suite green.

## Task 4: adjudication and recommendation criteria

Files: cli.py, benchmark_score.py and targeted tests.
Prevalidate all adjudication references and labels before persistence. Persist
an atomic verdict replacement with pending recoverable audit events; publish
events idempotently by event_id and recover on subsequent adjudication. This
avoids pretending two files can be replaced atomically as one transaction.
Add red/green tests for invalid second references, persistence failures and
recovery. Keep old verdicts and JSONL histories readable.

Recommendation eligibility: balanced complete pack, free routes, at least two
origins, no unsafe approvals, at least 80% actionable, at least 80% of correct
cases verified, and no missed injected blocks. Rank eligible candidates by
false rejections, unavailability and latency. These are conservative gates for
this pack, not statistical reliability guarantees. Test always-revise,
missed-block, boundary eligibility and existing valid candidates.
Expected: targeted tests and full suite pass.

## Task 5: documentation, validation and review

Update README, contribution guidance, integration docs and unreleased notes.
Explain provider labels as proxies, requested versus observed model identity,
partial artifact coverage, grounded excerpts versus interpretation, source
traceability versus source verification, single-provider blocking exception,
and recommendation thresholds. Add adversarial/coverage fixtures; never claim
general accuracy from synthetic tests.
Run full offline tests, source/wheel build, wheel content checks, twine check,
git diff --check and an independent whole-branch code review. Fix significant
review findings with regression tests. Commit locally and report exact hash,
diff, tests, limitations and readiness for separately approved publication.

## Review focus

Check cross-session shared-file ordering, metadata stripping/content digest
scope, truncated and omitted artifacts, stale approval, evidence compatibility,
model aliases/variants, redirects and exception sanitization, duplicate config
corroboration, audit-write interruption/recovery, denominator thresholds and
existing CLI/Hermes behavior. No live model calls are permitted.

## Publication follow-up

After local commit `f88bc49`, the user explicitly authorized pushing this branch,
opening a draft consolidation PR, updating relevant documentation and leaving
cross-reference comments on PRs 5/6/7. Verify the remote head and monitor the full
CI matrix for that exact revision, fixing relevant failures without rewriting
shared history. Existing PRs stay open. Merge, release/deployment and live-model
calls remain outside this authorization.
