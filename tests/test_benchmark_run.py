import json

import pytest

from agentjury.benchmark import Candidate, job_key, prepare, run
from agentjury.benchmark_cases import BenchmarkCase
from agentjury.judges.base import Completion, Judge
from agentjury.panel import Panel


class StubJudge(Judge):
    def __init__(self, role="accuracy", model="one:free", provider="vendor", replies=None):
        super().__init__(role, model)
        self.provider = provider
        self.params = {"route": "openrouter"}
        self.replies = list(replies or [])
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        reply = self.replies.pop(0) if self.replies else '{"vote":"approve","score":9,"reason":"fine","findings":[]}'
        if isinstance(reply, BaseException):
            raise reply
        return Completion(reply)


def _case(id="a", output="4"):
    return BenchmarkCase(id=id, task="Calculate 2 + 2", output=output, label="correct")


def _candidate(judges, spec="panel"):
    return Candidate(spec, Panel(judges))


def test_shared_judge_called_once_and_role_changes_job(tmp_path):
    shared = StubJudge()
    second = StubJudge("critic", "two:free", "other")
    panels = [_candidate([shared], "one"), _candidate([shared, second], "two")]
    cases = [_case(), _case("b", "5")]
    report = run(cases, "pack", panels, report_path=tmp_path / "run.json")
    assert report["state"] == "complete"
    assert len(report["jobs"]) == 4
    assert shared.calls == 2
    assert second.calls == 2


def test_cap_stops_retry_and_resume_skips_success(tmp_path):
    judge = StubJudge(replies=[RuntimeError("secret error"), '{"vote":"approve","score":9,"reason":"fine","findings":[]}'])
    path = tmp_path / "run.json"
    candidate = _candidate([judge])
    first = run([_case()], "pack", [candidate], report_path=path, max_calls=1)
    assert first["state"] == "partial"
    assert first["jobs"] == {}
    assert first["calls_total"] == 1
    assert json.loads(path.read_text())["calls_total"] == 1
    second = run([_case()], "pack", [candidate], report_path=path, max_calls=1, resume=True)
    assert second["state"] == "complete"
    assert judge.calls == 2
    run([_case()], "pack", [candidate], report_path=path, resume=True)
    assert judge.calls == 2


def test_cap_between_bad_reply_and_repair_leaves_pending(tmp_path):
    judge = StubJudge(replies=["bad", '{"vote":"approve","score":9,"reason":"fine","findings":[]}'])
    candidate = _candidate([judge])
    result = run([_case()], "pack", [candidate], report_path=tmp_path / "x.json", max_calls=1)
    assert result["state"] == "partial"
    assert result["jobs"] == {}
    assert judge.calls == 1


def test_failure_is_safe_and_only_retried_when_requested(tmp_path):
    class NoisyError(RuntimeError):
        status_code = 429

    judge = StubJudge(replies=[NoisyError("secret key https://private.invalid") for _ in range(2)])
    candidate = _candidate([judge])
    path = tmp_path / "x.json"
    report = run([_case()], "pack", [candidate], report_path=path)
    assert report["state"] == "complete"
    assert "NoisyError" in report["jobs"][job_key(_case(), judge)]["error"]
    assert "429" in report["jobs"][job_key(_case(), judge)]["error"]
    assert "secret" not in path.read_text()
    run([_case()], "pack", [candidate], report_path=path, resume=True)
    assert judge.calls == 2
    run([_case()], "pack", [candidate], report_path=path, resume=True, retry_errors=True)
    assert judge.calls == 3


@pytest.mark.parametrize("changed", ["pack hash", "content", "panel"])
def test_resume_rejects_changed_input(tmp_path, changed):
    judge = StubJudge()
    candidate = _candidate([judge])
    path = tmp_path / "x.json"
    run([_case()], "pack", [candidate], report_path=path)
    cases = [_case(output="5")] if changed == "content" else [_case()]
    pack_hash = "other" if changed == "pack hash" else "pack"
    candidates = [_candidate([StubJudge(model="different:free")])] if changed == "panel" else [candidate]
    with pytest.raises(ValueError, match="resume"):
        run(cases, pack_hash, candidates, report_path=path, resume=True)


def test_duplicate_judge_and_bad_cap_rejected(tmp_path):
    judge = StubJudge()
    with pytest.raises(ValueError, match="duplicate"):
        run([_case()], "pack", [_candidate([judge, judge])], report_path=tmp_path / "x.json")
    with pytest.raises(ValueError, match="max-calls"):
        run([_case()], "pack", [_candidate([judge])], report_path=tmp_path / "x.json", max_calls=0)


def test_report_redacts_echoed_case_and_configured_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-secret-123")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "https://private.invalid/v1")
    reason = "Calculate 2 + 2 dummy-secret-123 https://private.invalid/v1"
    judge = StubJudge(replies=[json.dumps({"vote": "approve", "score": 9, "reason": reason, "findings": []})])
    path = tmp_path / "x.json"
    run([_case()], "pack", [_candidate([judge])], report_path=path)
    saved = path.read_text()
    assert "Calculate 2 + 2" not in saved
    assert "dummy-secret-123" not in saved
    assert "https://private.invalid/v1" not in saved


def test_default_endpoint_url_is_redacted_from_model_reason(tmp_path):
    reason = "Reviewer quoted https://openrouter.ai/api/v1"
    judge = StubJudge(replies=[json.dumps({"vote": "approve", "score": 9, "reason": reason, "findings": []})])
    path = tmp_path / "x.json"
    run([_case()], "pack", [_candidate([judge])], report_path=path)
    assert "https://openrouter.ai/api/v1" not in path.read_text()


def test_sanitized_compatible_error_preserves_http_status(tmp_path):
    judge = StubJudge(replies=[RuntimeError("openrouter model x: RateLimitError, HTTP 429") for _ in range(2)])
    result = run([_case()], "pack", [_candidate([judge])], report_path=tmp_path / "x.json")
    assert result["jobs"][job_key(_case(), judge)]["error"] == "RuntimeError HTTP 429"


def test_duplicate_panel_specs_are_rejected_before_calls(monkeypatch):
    monkeypatch.setattr("agentjury.benchmark.build_panel", lambda spec: Panel([StubJudge()]))
    with pytest.raises(ValueError, match="duplicate panel"):
        prepare([_case()], ["same", "same"])


def test_interrupted_retry_keeps_checkpoint_partial(tmp_path):
    judge = StubJudge(replies=[RuntimeError("first"), RuntimeError("second")])
    candidate = _candidate([judge])
    path = tmp_path / "x.json"
    run([_case()], "pack", [candidate], report_path=path)
    judge.replies = [KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        run([_case()], "pack", [candidate], report_path=path, resume=True, retry_errors=True)
    saved = json.loads(path.read_text())
    assert saved["state"] == "partial"
    assert saved["jobs"] == {}
    assert saved["calls_total"] == 3
