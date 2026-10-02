# Capped OpenRouter diagnostic transport

This operator-only module adds sanitized diagnostics to the stopped synthetic
experiment's transport. It is excluded from the installed product wheel and
included in the source archive alongside its offline tests. Importing it does
not dispatch requests. There is no inference driver or automatic resumption.
Any new paid run needs separate authorization and a newly frozen plan.

`CappedTransport` wraps the native adapter's opener with the original destination,
prompt, timeout, routing, cost, model and completion guards. `Ledger` refuses an
existing journal. Each dispatch requires a persisted conservative reservation.
An HTTP, provider, accounting or completion failure halts the shared ledger.
The wrapper returns unchanged response bytes only after all guards pass.

The journal records validation stage, a fixed error category, actual HTTP status
when available, allowlisted model/provider/finish labels, response shapes,
validated token counts, reported cost and conservative reservations. Unknown
labels become `unrecognized`; absent finish fields remain distinguishable. Generation,
request and case identifiers are SHA-256 fingerprints, never raw values.
Prompts, response content, reasoning, refusal/error text, request headers and
unknown exception text or class names are omitted. Fingerprints permit equality
comparison; they do not make low-entropy identifiers anonymous.

`unsupported_controls` requires an explicit known machine error code in a
decoded provider response. An HTTP 400 alone is `http_failure`; it is not proof
that a particular control was unsupported. No error body is read or logged.
Unknown native finish values still fail the unchanged completion guard.

Run offline checks from the repository root:

```powershell
python -m pytest tests/test_capped_diagnostics.py tests/test_capped_guard_preservation.py -q
```

See [the diagnostic investigation](../../docs/openrouter-diagnostic-followup.md)
for the actual test history, billing observations and remaining limitations.
