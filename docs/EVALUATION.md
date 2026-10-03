# Evaluation and verdict meaning

AgentJury asks blind reviewers for opinions and aggregates them deterministically.
Offline tests verify contracts and regressions; they do not measure live model
accuracy. [Validation evidence](REVIEW_INTEGRITY_VALIDATION.md) records exact
input commits, local tests, builds and current limits.

## Verdict rules

Default quorum is a strict majority of requested reviewers, including slots whose
calls fail or abstain: `floor(requested / 2) + 1`. Only non-abstaining valid reviews
count toward it. A configured mixed-provider panel must hear from at least two
providers. Failure of quorum or that provider floor gives `insufficient_jury`.

After those gates, votes are compared among participating voters. Ties or a
revision majority need revision. An approval majority with any blocking reviewer
also needs revision. Blocking findings from two providers produce `blocked`;
an intentionally single-provider panel can block with two distinct reviewer
configurations. One reviewer cannot block alone. Duplicate configurations and
known equivalent Ollama aliases within one route are rejected before calls.

The local reviewer-command guard can separately downgrade `verified` to
`needs_revision`. Warnings stay distinct from votes and findings. `verified`
means this configured jury approved the supplied material; it does not establish
ground truth, calibrated confidence or absence of correlated mistakes.

## Code-change verdicts

`agentjury change` uses the same rules. Its verdict means that the configured
jury approved the supplied diff, task and test log; reviewers cannot run the
code or see unchanged files beyond the diff context. The packaged
`correctness`, `security` and `tests` roles are new reviewer configurations
with their own configuration IDs, and no benchmark case yet covers code, so
there is no evidence about their accuracy. Findings are excerpt-checked against
the diff like any other output. A verdict describes the exact bytes it covered:
`agentjury change status` reports it as stale after any edit to a reviewed
file. Grade findings with `agentjury adjudicate` to build the evidence that
future reputation work needs.

## Benchmark gates and metrics

Use an explicitly labeled dataset and explicit candidate panels. Each distinct
case/configuration job is run once and reused across candidates. The default
20-call cap counts actual attempts, retries and repair, with resumable reports.
Benchmark runs call configured models; inspecting `benchmark-audit` reports is
offline. See the [README](../README.md#compare-free-juries) for commands.

A provisional free-panel recommendation requires all of these:

- Complete run and at least two cases of each label: correct, flawed, injected.
- All routes native Ollama or explicitly requested OpenRouter `:free` variants.
- At least two configured provider origins.
- Zero unsafe approvals of flawed/injected cases.
- At least 80% of all cases have actionable verdicts.
- At least 80% of correct cases are verified.
- Every injected case is blocked, including cases otherwise unavailable.

Unavailable verdicts are tracked separately from false rejections and unsafe
approvals. `missed_blocks` counts injected `needs_revision` results; the explicit
all-injected-blocked gate also disqualifies unavailable injections. Always-revise
panels cannot qualify. Eligible panels rank by false rejection, unavailability
and median reviewer latency; equal rankings are reported as ties. Suggestions
do not change the normal review panel. Free eligibility is a route convention,
not a promise of future availability or zero local compute cost.

The six starter cases are a smoke test. `benchmark-audit` summarizes vote errors,
shared mistakes and raw majority performance versus the best observed individual
on the same answered cases. Those descriptive counts are not a generalization
claim, correlation calibration or evidence that one panel beats every reviewer.

## Source audit and next empirical work

`source_audit` checks supplied text for source/date traceability when the task
requests a source for a time-sensitive number. It cannot open links, retrieve
publications or verify that a citation supports the claim. Exact excerpt checks
also do not prove interpretation. The private-credit example is intentionally
weakly sourced; see [examples](../examples/README.md).

The initial integrity fixes were validated offline; later authorized local
smokes and artifact-source experiments are recorded in the validation report.
They include a failed artifact-injection probe and do not qualify a production
panel. Before recommending one, use representative labeled tasks, held-out cases,
human grading of individual findings, and repeated runs under exact model/route
identities. Report false approvals, false rejections, abstentions/unavailability,
blocking recall, cost, latency and shared-error patterns. Model versions may
change behind aliases. Confidence/reputation weighting and hard whole-panel
deadlines remain separate design work, not validated features of this public alpha.
