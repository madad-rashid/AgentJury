# OpenRouter diagnostic follow-up - 2026-10-02

This follow-up starts from published PR8 head
`e23afeb8c79dab5f95348f14d537ba2c8764da38`. Product implementation remains
`dbbfb1fe7b7f24d3c0840b3c4185de12fff836a3`. No further paid inference,
retry, model substitution, cap change, top-up, merge or release occurred.

## Established logging cause and unresolved completion cause

The original frozen transport checked choice count/error, standard finish,
native finish and nonempty content before recording finish/content metadata.
Each branch stopped with the same `incomplete_completion` label. The outer
handler recorded only failure class/status. The captured journal therefore
cannot identify the precise original rejection branch. This is an established
harness observability defect, not proof of a product-adapter defect.

The separate [diagnostic transport](../experiments/openrouter/capped_transport.py)
records safe response shapes and allowlisted labels before rejection, and records
the actual validation stage plus a distinct category for each completion branch.
No product adapter, acceptance predicate, routing rule or budget ceiling changed.
The original frozen scripts and evidence were preserved byte for byte.

The new journal omits request/response content, reasoning, error/refusal text,
headers and raw identifiers, including on success. Unknown labels are redacted;
identifiers are fingerprinted. Only validated numeric usage is stored. Known
cost is retained when subsequent token or completion validation fails. A journal
write failure before dispatch prevents a request. Persistence errors after a
request may prevent durable diagnostics; this is a storage limitation, and the
caller must stop rather than resume an existing journal.

## Nonbillable billing reconciliation

One bounded round read generation, key and credits metadata at 19:46:33 UTC.
A single focused generation read at 19:47:18 UTC investigated newly exposed
model/token discrepancies. Four authenticated GETs in total; zero inference calls.
The existing credential stayed in memory/Authorization and was never logged or
changed. Account balances were not published. There was no continuing polling.

Generation `total_cost` and dedicated-key usage now both equal **$0.004636**,
matching the immediate response-reported amount. The dedicated key still has
the **$3 non-resetting cap** and remaining allowance **$2.995364**. The earlier
zero counters and HTTP 404 observations are retained as historical snapshots;
they were not evidence of a free call. Cost is now reconciled against the
available service accounting records, not independently audited payment data.
The old journal's conservative **$0.057344** reservation remains unchanged as a
historical record. This reconciliation does not authorize further spending.

The generation record reports `openai/gpt-6.1-sol-20260929`, whereas the immediate
response reported the requested `openai/gpt-6.1-sol` alias. Generation token counts
are 1266 prompt / 183 completion, versus immediate 1151 / 176. Both observations
are preserved; we do not substitute one for the other or infer why they differ.
Provider is OpenAI, `cancelled=false`, `is_byok=false`, and later
`finish_reason=stop`. The native finish field is present but outside the
allowlist, so its raw value was not published. This later metadata does not
recover the original choice/content payload or prove which original check failed.
There remains no semantic grade or comparative-model result for the stopped run.

### Sanitized immutable accounting observation

```json
{
  "observed_at_utc": "2026-10-02T19:46:33.386437+00:00",
  "additional_inference_calls": 0,
  "maximum_nonbillable_requests": 3,
  "reported_cost_usd": "0.004636",
  "retained_conservative_reservation_usd": "0.057344",
  "settled_billing_verified": true,
  "generation": {
    "total_cost": "0.004636",
    "tokens_prompt": "1266",
    "tokens_completion": "183",
    "native_tokens_reasoning": "0",
    "model_matches_request": false,
    "provider_matches_observation": true,
    "cost_matches_reported": true
  },
  "key": {
    "limit": "3",
    "limit_remaining": "2.995364",
    "usage": "0.004636",
    "limit_reset_is_null": true,
    "cap_unchanged": true,
    "usage_matches_reported": true
  },
  "credits": {
    "read_succeeded": true,
    "balance_nonnegative": true,
    "account_balance_recorded": false,
    "call_attribution_available": false
  }
}
```

### Sanitized focused generation observation

```json
{
  "observed_at_utc": "2026-10-02T19:47:18.964031+00:00",
  "additional_inference_calls": 0,
  "model": "openai/gpt-6.1-sol-20260929",
  "model_fingerprint": "0153e8637f8fb737470478cfcac81bfd931868f780a0fda25ac253e6576ee6ef",
  "finish_reason": "stop",
  "finish_reason_present": true,
  "native_finish_reason": "unrecognized",
  "native_finish_reason_present": true,
  "cancelled": false,
  "is_byok": false,
  "provider_name": "OpenAI"
}
```

## Offline verification and next separately authorized experiment

Test-first diagnostics produced 18 expected failures and one existing passing
accounting case before implementation. The first run encountered a permission
error in the default pytest temporary directory; a fresh workspace `--basetemp`
resolved that setup issue. Independent review found a surrogate-identifier
fingerprinting exception; two additional fixtures failed before surrogate-safe
encoding corrected it. Then 41 diagnostic cases plus 13 original guard
preservation cases passed (54 total), all synthetic and under the offline network
guard. Fixtures cover missing/multiple choices, errors, missing/null/unknown
finish fields, truncation, native finish disagreement, missing/typed/empty content,
model/provider mismatch, unsupported machine codes, HTTP 400/401/402/429/500,
malformed accounting/JSON, secret redaction, unchanged accepted bytes, and
reservation persistence failure. None contacts a provider or uses real credentials.

Full-suite, independent review and package results will be recorded in the PR
verification comment against the exact published follow-up head.

The next proposed live diagnostic is **one initial completion only** for the
same frozen original synthetic artifact case and exact OpenAI alias/direct route,
with the unchanged 90-second timeout, zero retries, 4096-token cap, low reasoning,
no fallback and all price/privacy controls. It must use the reviewed diagnostic
transport and a new journal, reserve $0.057344 before dispatch, and stop after
that single response whether accepted or rejected. No Claude call or remaining
panel cases are included. Freeze its plan, source hashes, credential cap and
authorization separately. This proposal has not been executed or approved as
part of this follow-up.
