# Examples

These files are illustrative inputs, not evidence of live reviewer accuracy.

- `task.md` / `output.md`: a private-credit answer with an undated "today" figure
  and an organization name rather than a traceable publication. This intentionally
  weak citation is useful for source-audit testing; the example is not current
  financial research. A judge cannot retrieve the source from this text.
- `injected_output.md`: an adversarial answer for the opt-in live test and offline
  guard checks. A local warning is not proof of exhaustive injection resistance.
- `roles.json`: sample custom-role definitions.
- `artifact_request.json`: schema 0.7 request with a wrong number in a file while
  the main output only says "Done." Use the Python API for artifact requests;
  the current CLI review command accepts task/output text files, not this JSON.

Load the artifact example without calling a model:

```python
from pathlib import Path
from agentjury import ReviewRequest

request = ReviewRequest.model_validate_json(
    Path("examples/artifact_request.json").read_text(encoding="utf-8")
)
```

A finding about the file would quote `"324"` with
`output_artifact_id: "answer-file"`, and quote `"323"` from `basis_source: "task"`.
AgentJury computes the artifact digest when the request is loaded. Checked
quotes establish provenance, not whether a reviewer has interpreted them correctly.

See [providers](../docs/PROVIDERS.md), [evaluation](../docs/EVALUATION.md) and
[security](../docs/SECURITY.md) before any separately authorized live run.
