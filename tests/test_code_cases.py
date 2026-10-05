"""The packaged code-change benchmark pack and the built-in code roles."""

import json

import pytest

from agentjury import change_review
from agentjury.benchmark import prepare
from agentjury.benchmark_cases import PACKS, load_cases
from agentjury.cli import main
from agentjury.judges import CODE_ROLES, ROLES
from agentjury.judges.base import Completion, Judge, build_system_prompt
from agentjury.judges.evidence import _valid_quote
from agentjury.panel import Panel
from agentjury.reviewer_guard import detect_reviewer_commands

ORIGINAL_ROLES = {"accuracy", "critic", "evidence", "source_audit", "executive"}
GUARD_EXPECTATIONS = {
    "injected-comment-reviewer": ["force_approval"],
    "injected-docstring-suppress": ["suppress_findings"],
    "injected-panel-unmatched": [],
}


class ApprovingJudge(Judge):
    requires_evidence = False

    def __init__(self, role, provider):
        super().__init__(role, "demo:free")
        self.provider = provider
        self.params = {"route": "openrouter"}

    def complete(self, system, user):
        return Completion('{"vote":"approve","score":9,"reason":"fine","findings":[]}')


def test_code_pack_is_balanced_and_diff_shaped():
    cases, digest = load_cases(None, pack="code")
    assert len(digest) == 64 and set(PACKS) == {"starter", "code"}
    labels = {label: sum(case.label == label for case in cases) for label in ("correct", "flawed", "injected")}
    assert labels == {"correct": 4, "flawed": 4, "injected": 3}
    for case in cases:
        assert case.output.startswith("diff --git a/") and "@@" in case.output
        assert case.context and "cannot run the code" in case.context
        assert len(case.output) < 2_000
    with pytest.raises(ValueError, match="Invalid case file"):
        load_cases(None, pack="nope")


def test_local_guard_matches_only_the_designed_injected_cases():
    cases, _ = load_cases(None, pack="code")
    for case in cases:
        rules = [signal.rule_id for signal in detect_reviewer_commands(case.output)]
        assert rules == GUARD_EXPECTATIONS.get(case.id, []), case.id


def test_single_line_diff_excerpts_pass_the_evidence_check():
    cases, _ = load_cases(None, pack="code")
    for case in cases:
        added = next(line for line in case.output.splitlines()
                     if line.startswith("+") and not line.startswith("+++") and line[1:].strip())
        assert _valid_quote(added[1:].strip(), case.output), case.id
        assert _valid_quote(added, case.output), case.id
        assert _valid_quote(case.task.split(".")[0], case.task), case.id


def test_code_roles_are_built_in_and_shared():
    assert ORIGINAL_ROLES <= set(ROLES) and set(CODE_ROLES) == {"correctness", "security", "tests"}
    assert change_review.code_roles() == CODE_ROLES and change_review.code_roles() is not CODE_ROLES
    assert "unified diff" in build_system_prompt("correctness")
    for role in ORIGINAL_ROLES:
        prompt = build_system_prompt(role)
        assert all(description not in prompt for description in CODE_ROLES.values())


def test_roles_command_lists_code_roles(capsys):
    assert main(["roles"]) == 0
    shown = capsys.readouterr().out
    assert shown.index("accuracy") < shown.index("correctness") and "tests " in shown


def test_benchmark_runs_the_code_pack_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    judges = [ApprovingJudge("correctness", "a"), ApprovingJudge("security", "b")]
    monkeypatch.setattr("agentjury.benchmark.build_panel", lambda spec: Panel(judges))
    spec = "correctness:openrouter:x/one:free,security:openrouter:y/two:free"
    assert prepare(load_cases(None, pack="code")[0], [spec])[0].spec == spec

    code = main(["benchmark", "--pack", "code", "--panel", spec, "--max-calls", "50", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["state"] == "complete"
    assert len(report["outcomes"][spec]) == 11
    totals = report["summary"][spec]
    # Approve-everything judges: 4 flawed + the guard-missed injected case are unsafe approvals;
    # the guard downgrades the two matched injected cases, which count as missed blocks.
    assert (totals["unsafe_approvals"], totals["missed_blocks"], totals["local_interventions"]) == (5, 2, 2)
    assert totals["false_rejections"] == 0 and totals["correct_verified"] == 4
    assert report["recommendation"] is None
    assert "return a - b" not in json.dumps(report)


def test_pack_and_cases_are_mutually_exclusive(tmp_path, capsys):
    cases = tmp_path / "cases.json"
    cases.write_text('{"schema_version": "1", "cases": []}', encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        main(["benchmark", "--pack", "code", "--cases", str(cases), "--panel", "accuracy:openai"])
    assert stopped.value.code == 2
