"""Offline analysis of saved benchmark votes."""

import hashlib
import importlib
import json

import pytest

from agentjury.cli import main


def audit_report(report):
    return importlib.import_module("agentjury.benchmark_audit").audit_report(report)


def _report():
    cases = [
        {"id": "good-1", "label": "correct", "hash": "hash-1"},
        {"id": "bad-1", "label": "flawed", "hash": "hash-2"},
        {"id": "injected-1", "label": "injected", "hash": "hash-3"},
        {"id": "good-2", "label": "correct", "hash": "hash-4"},
    ]
    votes = {
        "a": ("approve", "approve", "revise", "revise"),
        "b": ("approve", "approve", "approve", "approve"),
        "c": ("revise", "revise", "revise", "approve"),
    }
    jobs = {}
    for case_index, case in enumerate(cases):
        for judge_id, judge_votes in votes.items():
            key = hashlib.sha256(f"{case['hash']}:{judge_id}".encode("ascii")).hexdigest()
            jobs[key] = {"review": {
                "judge": f"{judge_id}/openrouter/demo:free", "provider": judge_id,
                "vote": judge_votes[case_index], "reason": "PRIVATE ANSWER TEXT",
            }}
    return {
        "schema_version": "1", "state": "complete", "cases": cases,
        "panels": [{"spec": "panel-abc", "config_ids": ["a", "b", "c"],
                    "providers": ["a", "b", "c"]}],
        "jobs": jobs,
    }


def _job_key(case, judge_id):
    return hashlib.sha256(f"{case['hash']}:{judge_id}".encode("ascii")).hexdigest()


def test_audit_counts_individual_and_shared_errors_without_reasons():
    result = audit_report(_report())

    assert result["judges"]["a"]["correct"] == 2
    assert result["judges"]["a"]["false_approvals"] == 1
    assert result["judges"]["a"]["false_rejections"] == 1
    assert result["judges"]["b"]["false_approvals"] == 2
    assert result["judges"]["c"]["false_approvals"] == 0
    shared = next(pair for pair in result["pairs"] if pair["judge_ids"] == ["a", "b"])
    assert shared["compared"] == 4
    assert shared["both_wrong"] == ["bad-1"]
    assert shared["both_unsafe_approvals"] == ["bad-1"]
    assert "PRIVATE ANSWER TEXT" not in json.dumps(result)


def test_audit_compares_raw_majority_with_best_single_on_same_cases():
    result = audit_report(_report())
    panel = result["panels"]["panel-abc"]

    assert panel["common_cases"] == 4
    assert panel["majority"] == {
        "correct": 3, "false_approvals": 1, "false_rejections": 0,
        "ties": 0,
    }
    assert panel["best_judge_ids"] == ["c"]
    assert panel["best_single"] == {
        "correct": 3, "false_approvals": 0, "false_rejections": 1,
    }


def test_audit_keeps_errors_abstentions_and_pending_out_of_comparison():
    report = _report()
    report["state"] = "partial"
    report["jobs"][_job_key(report["cases"][2], "a")] = {"error": "RuntimeError HTTP 429"}
    report["jobs"][_job_key(report["cases"][3], "b")]["review"]["vote"] = "abstain"
    del report["jobs"][_job_key(report["cases"][1], "c")]

    result = audit_report(report)

    assert result["judges"]["a"]["unavailable"] == 1
    assert result["judges"]["b"]["unavailable"] == 1
    assert result["judges"]["c"]["pending"] == 1
    assert result["panels"]["panel-abc"]["common_cases"] == 1
    assert result["panels"]["panel-abc"]["best_judge_ids"] == ["a", "b"]


def test_audit_distinguishes_shared_false_rejections_from_unsafe_approvals():
    report = _report()
    report["jobs"][_job_key(report["cases"][3], "b")]["review"]["vote"] = "revise"

    shared = next(pair for pair in audit_report(report)["pairs"]
                  if pair["judge_ids"] == ["a", "b"])
    assert shared["both_wrong"] == ["bad-1", "good-2"]
    assert shared["both_unsafe_approvals"] == ["bad-1"]


def test_audit_counts_two_reviewer_ties_as_unresolved():
    report = _report()
    report["panels"][0]["config_ids"] = ["a", "b"]
    report["panels"][0]["providers"] = ["a", "b"]

    majority = audit_report(report)["panels"]["panel-abc"]["majority"]
    assert majority == {"correct": 1, "false_approvals": 1,
                        "false_rejections": 0, "ties": 2}


def test_audit_names_reviewer_with_no_successful_review_from_panel_spec():
    report = _report()
    report["state"] = "partial"
    report["panels"][0]["spec"] = (
        "accuracy:openrouter:vendor/a:free,critic:openrouter:vendor/b:free,"
        "executive:openrouter:vendor/c:free"
    )
    for case in report["cases"]:
        del report["jobs"][_job_key(case, "c")]

    result = audit_report(report)

    assert result["judges"]["c"]["name"] == "executive:openrouter:vendor/c:free"
    assert result["judges"]["c"]["pending"] == 4


def test_audit_command_reads_saved_report_without_provider_setup(tmp_path, monkeypatch, capsys):
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    monkeypatch.setattr("agentjury.benchmark.prepare", lambda *_: pytest.fail("provider setup"))

    assert main(["benchmark-audit", str(path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["panels"]["panel-abc"]["common_cases"] == 4
    assert "PRIVATE ANSWER TEXT" not in json.dumps(result)


def test_audit_rejects_invalid_report(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":"9"}', encoding="utf-8")

    assert main(["benchmark-audit", str(path)]) == 5
    assert "Invalid benchmark report" in capsys.readouterr().err


def test_audit_rejects_unknown_vote():
    report = _report()
    report["jobs"][_job_key(report["cases"][0], "a")]["review"]["vote"] = "maybe"

    with pytest.raises(ValueError, match="Invalid benchmark report"):
        audit_report(report)


@pytest.mark.parametrize("field", ["cases", "panels"])
def test_audit_rejects_empty_metadata(field):
    report = _report()
    report[field] = []

    with pytest.raises(ValueError, match="Invalid benchmark report"):
        audit_report(report)


def test_audit_rejects_complete_report_with_missing_job():
    report = _report()
    del report["jobs"][_job_key(report["cases"][0], "a")]

    with pytest.raises(ValueError, match="Invalid benchmark report"):
        audit_report(report)


def test_audit_rejects_complete_report_with_null_job():
    report = _report()
    report["jobs"][_job_key(report["cases"][0], "a")] = None

    with pytest.raises(ValueError, match="Invalid benchmark report"):
        audit_report(report)


def test_audit_text_escapes_controls_in_saved_labels(tmp_path, capsys):
    report = _report()
    report["cases"][1]["id"] = "bad\nFAKE OK\x1b[31m"
    report["panels"][0]["spec"] = "panel\nFAKE OK\x1b[31m"
    report["jobs"][_job_key(report["cases"][0], "a")]["review"]["judge"] = (
        "judge\nFAKE OK\x1b[31m"
    )
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert main(["benchmark-audit", str(path)]) == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\nFAKE OK" not in output
    assert "\\nFAKE OK\\u001b" in output
