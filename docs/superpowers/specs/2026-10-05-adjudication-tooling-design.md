# Adjudication tooling, code benchmark pack and display consolidation

## Purpose

Reputation weighting and calibrated confidence need human grades of individual
findings, and the only source of those grades is people adjudicating real
reviews. Today a grade is recorded with `agentjury adjudicate`, but nothing
shows what still needs grading, nothing lets a tester share grades without
sharing the reviewed text, and nothing counts the grades that exist. Reviewer
accuracy on code is also unmeasured because no benchmark case is a code change.
This change adds the collection and counting tools, a labelled code case pack,
and consolidates duplicated display and storage helpers. It activates no
weighting and changes no verdict, schema or rubric.

## Commands

All three live under `agentjury adjudication`. They read verdict directories
the same way `verdicts` and `adjudicate` do (`--dir`, else
`AGENTJURY_VERDICT_DIR`, else `.agentjury/verdicts`); `--dir` is repeatable so
Hermes and repository directories can be read together. They make no network
calls and never modify a verdict.

### `agentjury adjudication pending [--dir DIR]... [-n N] [--json]`

Lists findings without a grade, so human attention goes where the information
is. A finding is **contested** when the panel's voters were not unanimous, when
its severity is `major` or `blocking` in a `verified` verdict (the panel
overruled its reviewer), or when it is `blocking` in a `needs_revision` or
`blocked` verdict (it decided the outcome). Order: contested first, then
severity (blocking, major, minor), then newest verdict first, then reviewer
order, then finding number. Each verdict is a group headed by run ID, request
ID, date, status, votes and task type; each finding line shows the reviewer,
the number as `agentjury adjudicate` expects it, the severity, the escaped
text and the exact `agentjury adjudicate … --finding N <label>` command. A
verdict without a producer grade ends with the `--producer-verdict` command.
`-n` limits the number of verdicts shown; the total pending count is always
printed. Exit 0.

### `agentjury adjudication export [--dir DIR]... [--out FILE]`

Writes one JSON document containing everything reputation and calibration
work needs and nothing that was reviewed. The document is built from an
explicit allowlist; no field is copied by default.

Per verdict: `run_id`, `request_id`, `panel_id`, `schema_version`,
`created_at`, `task_type`, `domain`, `producer.framework`, `producer.provider`,
`producer.model`, `requested`, `responded`, `abstained`, `quorum`, `up`,
`down`, `score`, `consensus`, `diversity`, `confidence`, `status`,
`local_signal_rules` (rule IDs only), `local_guard_applied`, `error_count`,
`artifact_coverage` as counts per coverage kind, `human_verdict`,
`adjudicated_at`.

Per review: `review_id`, `config_id`, `judge`, `role`, `provider`, `model`,
`observed_model`, `vote`, `score`, `self_confidence`, `rubric_version`,
`prompt_hash`, `params` restricted to known non-secret keys (`route`,
`transport`, `format`, `endpoint_hash`, `requested_model`,
`completion_policy`, `timeout`, `max_tokens`, `effort`, `thinking`),
`latency_ms`, `tokens_in`, `tokens_out`, `human_review.verdict`,
`human_review.reviewed_at`.

Per finding: `id`, `severity`, `has_evidence`, `basis_source`,
`adjudication`, `adjudicated_at`.

Per adjudication event from `adjudications.jsonl`: `event_id`, `at`, `kind`,
`run_id`, `request_id`, `review_id`, `config_id`, `judge`, `finding_id`,
`old`, `new`.

Never exported: task, output, context, artifacts, finding text, evidence
quotes, reviewer reasons, error text, local-signal excerpts, artifact names,
notes, `producer.agent`, adjudicator identity, response IDs, file paths and
unknown `params` keys. Unpublished `pending_adjudication_events` are counted,
not exported. The document records `kind`, `version`, `agentjury_version`,
`exported_at` and the number of verdicts, reviews, findings, graded findings
and events; the command prints that summary. A test fills every text field of
a verdict, its events and its params with sentinels and asserts none appears
in the export.

### `agentjury adjudication stats [--dir DIR]... | --from EXPORT [--json]`

Descriptive counts from local verdicts or from an export file, grouped by
reviewer configuration (`config_id` with judge, role, provider, model and
rubric version) and, within it, by task type: findings total and graded;
`correct`, `partially_correct` and `wrong`; reviews graded `agree`, `partial`
and `disagree`; and, on verdicts with a producer grade, votes that approved a
`flawed` output or revised a `correct` one. Totals cover verdicts, producer
grades and jury status against producer grade. The output states that these
are descriptive counts from graded findings, not reputation weights or
calibrated probabilities, and nothing in the package reads them to change a
verdict. Reviewer configurations are reported separately even when they share
a model, because `config_id` is the identity reputation will use.

## Code benchmark pack

`agentjury/data/code_cases.json` is a schema 1 case pack where each output is a
unified diff and each task is the requirement the diff should meet, with a
context note in the style of `agentjury change` scope notes (reviewers see only
the diff and cannot run code). Labels follow the existing meaning: `correct`
(the diff meets the task), `flawed` (a logic or security defect the diff
shows) and `injected` (the diff carries text that addresses reviewers). Nine
to twelve cases, three or four per label, small Python functions, no external
dependencies. Flawed cases include an off-by-one, an inverted condition, a
wrong operator and a shell-injection path. Injected cases include at least two
that the local reviewer-command guard matches and one phrased so it does not,
so the pack measures the models, not only the guard. Every excerpt a reviewer
could need sits on one diff line.

`agentjury benchmark` gains `--pack {starter,code}`, mutually exclusive with
`--cases`. The three code roles become built-in: `judges/base.py` loads
`data/change_roles.json` into `ROLES` at import, `agentjury roles` lists them,
`change_review` uses the same source, and benchmark panels can name them.
Existing roles and their configuration IDs are unchanged. Running the pack
still costs provider calls and is not part of the test suite; tests load the
pack, check labels and guard behaviour, and replay it through the benchmark
runner with fake judges.

## Consolidation

- `agentjury/display.py` builds verdict lines once, with options for numbered
  findings, file hints and a coverage note. `cli.print_verdict` and
  `change_review.verdict_lines` use it; their current output stays byte for
  byte identical, which existing tests pin. Hermes keeps its own compact
  `/jury` format.
- `agentjury/local_store.py` holds `atomic_write` and `resolve_verdict_dir`;
  `cli` and `change_review` use them. Hermes keeps its own copy because the
  plugin folder is installed separately against the published 0.5.0 core.
- `judges.base.parse_roles(text)` validates a roles document; `load_roles` and
  `change_review` use it.
- The unused import and unused test locals that pyflakes reports in the Hermes
  files are removed.

## Verification

Offline tests with fake judges and crafted verdicts: pending ordering for each
contested rule, numbering that matches `adjudicate`, limits and JSON output;
the export sentinel test, allowlisted params, event filtering, multi-directory
reads and unreadable files skipped with a count; stats from verdicts and from
an export agree, false-approval and false-rejection counting, and the
disclaimer text; the code pack loads, each label's guard behaviour is as
designed, the roles are built in and configuration IDs of existing roles are
unchanged; display consolidation keeps existing outputs; the full suite and a
package build pass. No live provider call.

## Limits

Grades are self-reported by whoever runs `adjudicate`; the export does not
authenticate them. Counts per configuration stay small for a long time and
fragment whenever a rubric, prompt or model changes. The code pack is tiny and
synthetic; a good score on it is not evidence of accuracy on real changes.
