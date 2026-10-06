# AgentJury v0.5.1

A feature release on the 0.5 public alpha. Schema and review policy stay at
0.7, and no verdict, rubric, aggregation, quorum, provider-floor or blocking
rule changes. Existing reviewer configuration IDs are unchanged, so benchmark
and adjudication history carries over.

## Added

- `agentjury change candidates|prepare|send|status`: explicit, previewed
  reviews of a Git code change. `prepare` builds the diff of selected changed
  files, leaves out secret-named files, symlinks, submodules, lockfiles and
  binary content, refuses on a local secret-scan match, and writes a preview of
  the exact payload and destinations without contacting any reviewer. `send`
  submits a prepared review once, after checking a confirmation code, the
  reviewed file bytes and the reviewer configuration. `status` reports whether
  the reviewed files changed since. The new commands exit 6 for a refusal and
  `status` exits 7 for a stale review.
- The Claude Code plugin in `integrations/claude-code/` and a repository
  marketplace. Its user-invoked skills prepare reviews, show status, list
  ungraded findings and record user-stated grades; the user runs the send
  command, and a hook denies Claude-initiated sends.
- `correctness`, `security` and `tests` reviewer roles for code changes, built
  in and listed by `agentjury roles`. They are new, unbenchmarked reviewer
  configurations; `agentjury benchmark --pack code` is their first synthetic
  coverage, aimed at `correctness` and `security` panels.
- `agentjury adjudication pending|export|stats`: a grading queue that puts
  reviewer dissent first and spreads producer grades across confidence bands,
  with ready-to-edit `agentjury adjudicate` commands whose placeholders record
  nothing until replaced; a text-free JSON export of grades and reviewer
  identities built from an allowlist pinned by tests; and descriptive counts
  per reviewer configuration and task type, labelled as not being reputation
  weights. `export` and `stats` exit 5 on invalid input.
- `agentjury benchmark --pack code`: eleven labelled unified-diff cases, two
  injected ones caught by the local check and one not. Reports record their
  case source so `--resume` needs no repeated `--pack`.
- `agentjury --version`, printing the package and schema versions.

## Changed

- `agentjury review` saves to `--dir` or `AGENTJURY_VERDICT_DIR` like the
  other verdict commands, writes verdict files atomically with LF line endings
  on every platform, and shows `[graded <label>]` after graded findings.
- The CLI and Hermes `/jury` displays escape control characters in reviewer
  names, reasons, findings and errors.
- Verdict display, atomic writes and verdict-directory resolution are shared
  between `review` and `change`. The Hermes plugin keeps its own copies so it
  still runs against the 0.5.0 core.
- A roles file that is not valid JSON or not an object of strings now exits
  with its message instead of a traceback.
- The Hermes plugin manifest in `integrations/hermes/`, installed from a
  checkout rather than from the wheel, depends on published
  `agentjury>=0.5.0,<0.6` instead of a Git pin. Re-copy or relink the plugin
  folder when upgrading.

## Runtime behavior

No protocol schema, rubric, aggregation or provider change. Nothing reads
human grades to change a verdict; the new counts are descriptive. Confidence
remains an uncalibrated heuristic. Change-review verdicts are schema 0.7
verdicts whose `artifact_coverage` lists each reviewed path with its
working-tree digest, so `agentjury verdicts` and `agentjury adjudicate` work
on them unchanged.

## Limits

The code benchmark pack is tiny and synthetic; a good score is not evidence of
accuracy on real changes. The local reviewer-command guard has a short cue
list and is not an injection scanner. The adjudication export discloses the
operator-chosen labels it carries (judge, role, model, task type, domain,
producer) and drops adjudicator identity, so grader disagreement cannot be
measured from an export. See `docs/SECURITY.md` and `docs/EVALUATION.md`.

## Public alpha

AgentJury remains in public alpha. Feedback on false positives, missed errors,
reviewer disagreement, latency, cost and integration behavior is especially
useful.

GitHub: https://github.com/madad-rashid/AgentJury
