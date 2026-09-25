import json
import sys

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
    help_text = capsys.readouterr().out
    assert "--max-calls" in help_text
    assert "unfinished job" in help_text


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


def test_benchmark_explains_missing_openrouter_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentjury.cli.load_dotenv", lambda: False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["benchmark", "--panel", "accuracy:openrouter:vendor/model"]) == 5
    assert "Set OPENROUTER_API_KEY" in capsys.readouterr().err


def test_benchmark_explains_unknown_role(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["benchmark", "--panel", "critc:ollama:qwen3:8b"]) == 5
    assert "Unknown role" in capsys.readouterr().err


def test_review_explains_missing_openai_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "openai", None)
    (tmp_path / "task.txt").write_text("Check this", encoding="utf-8")
    (tmp_path / "output.txt").write_text("Answer", encoding="utf-8")
    with pytest.raises(SystemExit, match=r'pip install "agentjury\[openai\]"'):
        main(["review", "task.txt", "output.txt", "--panel", "accuracy:ollama:local"])


def test_benchmark_explains_missing_openai_package(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "openai", None)
    assert main(["benchmark", "--panel", "accuracy:ollama:local"]) == 5
    assert 'pip install "agentjury[openai]"' in capsys.readouterr().err


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


@pytest.mark.parametrize("factory_error", [ImportError("missing SDK"), RuntimeError("missing key")])
def test_panel_setup_errors_return_configuration_code(tmp_path, monkeypatch, capsys, factory_error):
    monkeypatch.chdir(tmp_path)

    def broken_panel(spec):
        raise factory_error

    monkeypatch.setattr(benchmark, "build_panel", broken_panel)
    assert main(["benchmark", "--panel", "accuracy:openai"]) == 5
    captured = capsys.readouterr()
    assert "configuration" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert not (tmp_path / ".agentjury").exists()


def test_human_summary_shows_completion_and_median_latency(fake_panels, capsys):
    assert main(["benchmark", "--panel", "demo"]) == 0
    output = capsys.readouterr().out
    assert "completed 6/6" in output
    assert "median judge latency" in output


def test_equal_panels_are_labeled_as_tied(fake_panels, monkeypatch, capsys):
    import agentjury.cli as cli
    real_score = cli.score

    def tied_score(report, cases, candidates):
        report = real_score(report, cases, candidates)
        if report["state"] == "complete":
            report["recommendation"] = {"provisional": True, "panels": ["panel-a", "panel-b"]}
        return report

    monkeypatch.setattr(cli, "score", tied_score)
    assert main(["benchmark", "--panel", "panel-a", "--panel", "panel-b"]) == 0
    output = capsys.readouterr().out
    assert "Tied provisional" in output
    assert "--panel panel-a" in output
    assert "--panel panel-b" in output
