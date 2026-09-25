# Local Reviewer-Instruction Guard

## Purpose and evidence

AgentJury should avoid approving an answer that tries to instruct its reviewers. The current judge prompt tells models to treat the answer as untrusted, and the grounded-findings gate checks the excerpts behind any criticism. Neither helps when a weak panel approves an injected answer without producing findings. In a local starter-case test, `injected-forged-rubric` reached `verified` with no findings.

The user chose false-approval prevention first. Success is a deterministic, local check that changes an otherwise verified verdict to `needs_revision` when the submitted answer contains an explicit instruction aimed at the reviewers. The signal must be visible separately from model reviews. It must use no provider calls and must not claim to find every prompt injection.

## Approaches considered

- Ask every model judge for an additional safety judgment. This relies on the same weak reviewers that missed the instruction and makes their output contract larger.
- Add a separate safety reviewer. This spends scarce free-model requests and may still miss the instruction.
- Check the answer locally for narrow reviewer-directed commands, then prevent a verified result when the check matches. This is the selected approach. It is predictable and costs no provider requests, but it may flag a legitimate quotation and cannot recognize every paraphrase. The user chose to flag quoted text and code blocks to favor safety.

## Detection contract

A small, standalone detector reads `ReviewRequest.output` only. It does not scan the task, context, model review text, or attached artifacts. It uses Unicode NFKC normalization, case folding, and collapsed whitespace for matching, without treating Markdown quotations or fenced code as exempt. A match requires both a reviewer-related cue and a directive within 200 normalized characters of that cue. Cues include `reviewer`, `judge`, `jury`, and a reviewer `rubric` or grading instruction. The directive must tell the reviewer to approve or mark the answer verified, set or increase a score, ignore the task or a finding, or suppress reporting of the instruction. Imperative or obligation wording such as `return approve`, `must be marked verified`, or `do not report ... as a finding` counts; narrative text that merely mentions these words does not. An isolated word such as `approve`, or ordinary discussion of how reviews work, does not match.

The detector returns zero or more structured matches: a stable rule identifier (`force_approval`, `score_override`, or `suppress_findings`) and a short excerpt from the answer. It deduplicates overlapping matches, stores at most three matches, and limits each excerpt to 160 characters. Stored and printed excerpts have control characters escaped so the answer cannot inject terminal formatting. The detector makes no network or model calls and never changes a model review.

This is a deliberately narrow rule, not a general content-safety classifier. The two injected starter cases must match. Benign text mentioning reviewers, an ordinary approval request unrelated to AgentJury reviewers, and task/context text containing reviewer instructions must not match. Because the user chose safety for quoted examples, a matching command inside a quote or code block does match, even if it is presented as research material.

## Verdict data flow and status

`aggregate` runs the detector for each request so normal reviews and benchmark replay use the same rule. The verdict records the local matches in an optional field that defaults to empty when reading older verdict JSON. The field is expressly a local signal, not a `Finding` attributed to a judge or an extra vote. The existing `up`, `down`, score, consensus, diversity, confidence, and judge findings remain derived only from model reviews.

Existing status precedence remains: insufficient quorum or provider diversity yields `insufficient_jury`; two independent blocking sources yield `blocked`; a tie, majority revision, or one blocking source yields `needs_revision`. Only if those rules would yield `verified` does any local match change status to `needs_revision`. A local match never creates `blocked` on its own. It may still be recorded when another status wins so the warning is not lost.

The command-line summary and saved verdict make the local intervention explicit, including the matched rule and a sanitized short excerpt. They must say that the warning is from a local check, not from a model reviewer. A result with approving votes and `needs_revision` must therefore be understandable. Existing exit-code meanings remain unchanged. Older verdicts with no local field still load and render normally. Increment the protocol schema version from `0.5` to `0.6` for newly written records; reading a saved `0.5` verdict requires no migration.

## Benchmark reporting

Benchmark replay passes the case output through the same `aggregate` path. The report records whether the local check intervened for each completed outcome and counts interventions in a separate summary metric. It does not copy the matched excerpts into benchmark reports, following the existing practice of avoiding case text in those reports. An injected case rescued from `verified` by the local check is no longer an unsafe approval, but its model panel still missed an independent block; the benchmark's existing `missed_blocks` metric continues to show that weakness. Recommendations remain provisional and favor panels that independently identify injected answers. No benchmark or provider call is added by this feature.

## Verification and limits

Offline tests cover both injected starter examples, reviewer-command variants, benign near misses, quoted and fenced commands, task/context-only instructions, excerpt sanitization and caps, overlap deduplication, old-verdict loading, normal `verified` outcomes, quorum/provider-floor precedence, existing `blocked` outcomes, command-line display, and benchmark replay metrics. Tests must show that vote counts and confidence stay tied to the judges and that the detector causes no completion calls. Run the full test suite and package build after implementation.

No live OpenRouter run is required to accept this change. The user wants to preserve the limited free-call allowance. A later live probe can use an explicit small call cap after free requests are available again. This rule prevents a known class of reviewer-directed approval attempts; measured benchmark results should distinguish its local interventions from what the model panel actually caught.
