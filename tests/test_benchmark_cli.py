import json

import pytest

from agentjury import benchmark
from agentjury.cli import main
from agentjury.judges.base import Completion, Judge
from agentjury.panel import Panel


class CliJudge(Judge):
    def __init__(self, role, provider):
        super().__init__(role, "demo:free")
        self.provider = provider
        self.params = {"route": "openrouter"}
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return Completion('{"vote":"approve","score":9,"reason":"fine","findings":[]}')


@pytest.fixture
def fake_panels(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    judges = [CliJudge("accuracy", "a"), CliJudge("critic", "b")]
    monkeypatch.setattr(benchmark, "build_panel", lambda spec: Panel(judges))
    return judges


def test_benchmark_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["benchmark", "--help"])
    assert exc.value.code == 0
    assert "--max-calls" in capsys.readouterr().out


def test_benchmark_requires_explicit_panel():
    with pytest.raises(SystemExit) as exc:
        main(["benchmark"])
    assert exc.value.code == 2


def test_preflight_partial_resume_and_json(fake_panels, capsys):
    first = main(["benchmark", "--panel", "demo", "--max-calls", "1"])
    output = capsys.readouterr().out
    assert first == 4
    assert "distinct jobs" in output
    assert "maximum attempts" in output
    assert "call cap" in output
    assert "report" in output
    assert sum(j.calls for j in fake_panels) == 1
    report_path = next((__import__("pathlib").Path(".agentjury/benchmarks")).glob("*.json"))
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["state"] == "partial"
    assert "summary" in saved
    second = main(["benchmark", "--panel", "demo", "--resume", str(report_path), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert second == 0
    assert result["state"] == "complete"
    assert sum(j.calls for j in fake_panels) == 12


def test_invalid_dataset_stops_before_calls(fake_panels, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    assert main(["benchmark", "--cases", str(bad), "--panel", "demo"]) == 5
    assert sum(j.calls for j in fake_panels) == 0
    assert "case file" in capsys.readouterr().err


def test_duplicate_config_stops_before_calls(fake_panels, monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "build_panel", lambda spec: Panel([fake_panels[0], fake_panels[0]]))
    assert main(["benchmark", "--panel", "demo"]) == 5
    assert fake_panels[0].calls == 0
    assert "duplicate" in capsys.readouterr().err


def test_progress_and_report_do_not_echo_case_or_key(fake_panels, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-secret-123")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "https://private.invalid/v1")
    assert main(["benchmark", "--panel", "demo", "--max-calls", "1"]) == 4
    output = capsys.readouterr().out
    report_path = next((__import__("pathlib").Path(".agentjury/benchmarks")).glob("*.json"))
    for forbidden in ("dummy-secret-123", "https://private.invalid/v1", "Calculate 17 multiplied by 19"):
        assert forbidden not in output
        assert forbidden not in report_path.read_text(encoding="utf-8")


def test_cli_retry_errors_reuses_successful_jobs(fake_panels, capsys):
    judge = fake_panels[0]
    original = judge.complete

    def flaky(system, user):
        if judge.calls < 2:
            judge.calls += 1
            raise RuntimeError("temporary failure")
        return original(system, user)

    judge.complete = flaky
    assert main(["benchmark", "--panel", "demo", "--max-calls", "2"]) == 4
    capsys.readouterr()
    report_path = next((__import__("pathlib").Path(".agentjury/benchmarks")).glob("*.json"))
    assert main(["benchmark", "--panel", "demo", "--resume", str(report_path)]) == 0
    capsys.readouterr()
    before = sum(j.calls for j in fake_panels)
    assert main(["benchmark", "--panel", "demo", "--resume", str(report_path), "--retry-errors"]) == 0
    assert sum(j.calls for j in fake_panels) == before + 1
    assert all("review" in item for item in json.loads(report_path.read_text())["jobs"].values())
