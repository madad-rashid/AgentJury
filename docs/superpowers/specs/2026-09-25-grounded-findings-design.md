# Grounded Jury Findings

## Purpose and evidence

AgentJury's verdicts are only useful when their explanations are trustworthy. In a local paired test, a Qwen3 4B panel approved an accurate DeepSeek comparison and requested revision of a copy with one wrong price. Several individual findings nevertheless asserted errors that the supplied reference facts contradicted. A prompt-only change and two stricter prompt probes did not reliably stop these assertions. The prompt change was reverted.

The user chose verdict accuracy first and prefers an unavailable review to an unsupported factual criticism. Success means AgentJury does not count a new model review that cannot point to checkable text for its findings. The guard should use no additional provider calls beyond the existing single JSON-repair attempt. It cannot prove that a model interprets a genuine excerpt correctly, so the interface must not describe checked excerpts as verified facts.

## Approaches considered

- Stronger-model selection alone may improve reasoning but depends on free-provider availability and leaves individual findings unchecked.
- A second model to verify each finding consumes extra calls and can itself make mistakes.
- Require short evidence excerpts and validate their presence locally. This can reject invented or absent excerpts without another provider. It may make small-model reviews unavailable more often. This is the selected approach.

## Evidence contract

Every new finding returned by a judge includes its existing text and severity plus evidence:

```json
{
  "text": "DeepSeek output pricing is misstated.",
  "severity": "major",
  "evidence": {
    "output_quote": "Output: $12 per million",
    "basis_source": "context",
    "basis_quote": "peak prices $0.30 input, $1.20 output"
  }
}
```

`output_quote` is a short exact substring of the agent output. `basis_source` is `task`, `context`, `output`, or `reviewer_rule`. For `task`, `context`, and `output`, `basis_quote` is a short exact substring of that named section. `output` as a basis is for contradictions within the answer and needs a distinct quote. `reviewer_rule` is for attempts to manipulate the judge; its basis quote must match the fixed reviewer-manipulation rule in the system prompt. Task omissions can cite the task requirement and a representative part of the answer. Arithmetic errors can cite the operands in the task and the reported result in the output; this gate checks the excerpts' presence, not the arithmetic.

The prompt says that a URL in the agent output is not fetched by the judge. A model may only allege disagreement with a source when the relevant source text is supplied in the task or context. Recommendations clearly framed as opinions should not be reported as false measured claims. Judges should omit a finding they cannot ground in the material they actually received.

## Validation and failure behavior

`Judge.review` validates evidence after parsing the JSON and before creating a `Review`. Both quotes must be nonempty, bounded in length, and literal substrings of their declared sections, except that `reviewer_rule` uses the fixed rule text. The `context` source is invalid when no context was supplied. A `revise` vote needs at least one validated finding. A model response that violates the evidence contract uses the existing one repair round-trip with a short format correction. If the second response is still invalid, that judge fails; the panel's existing quorum and provider-floor rules decide whether a verdict is available. The failed response and its unsupported claims are not shown as findings.

The program must not silently delete individual findings and retain the model's vote, because that vote may depend on the deleted criticism. For accepted reviews, the user-facing reason is a neutral summary of the vote and finding count, rather than the model's unvalidated free-text reason. Findings remain attributed to the reviewer and are described as excerpt-checked allegations, not established facts. Human finding adjudication remains available.

The existing retry and JSON-repair budget still applies. Benchmark preflight and `--max-calls` continue to count every provider completion attempt, including the evidence repair. A failed evidence check appears as a sanitized judge error, not as a correct or incorrect case outcome.

## Storage, compatibility, and privacy

New findings may store the two short excerpts in normal local verdict JSON so a user can inspect them. The evidence field is optional when reading older saved verdicts and benchmark reports. New live judge responses must provide it. Change the prompt/rubric identity so old and new judge results are not reused as if they followed the same contract.

Benchmark reports remain local and ignored by Git. They record that evidence validation passed but omit the new excerpt fields, which would otherwise copy portions of user-supplied cases into the report. Existing redaction of model-generated finding text and secrets remains in force. The task, context, and output still go to only the providers the user explicitly selects.

## Verification

Offline tests cover literal match and mismatch for each evidence source, absent context, oversized or empty quotes, one repair attempt, failure after repair, `revise` without findings, old saved-verdict loading, sanitized benchmark errors, and unchanged quorum behavior. Tests use real judge parsing and panel aggregation with a controlled completion stub; they do not assert prompt wording alone.

Run the full test suite and package build. Then run the local good/wrong-price pair and at least one injected starter case. The live acceptance check inspects both case status and individual finding wording. A weak model may become unavailable; the required safety result is that an unsupported finding does not enter an accepted review. The benchmark continues to report unavailability separately from false approvals and false rejections.

This design checks that excerpts exist, not that the alleged contradiction is logically valid. Later human adjudications and multi-provider benchmark runs remain necessary to measure that remaining error.
