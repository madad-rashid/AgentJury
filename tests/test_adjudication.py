"""Pending findings, the text-free export and descriptive stats, on crafted verdicts. No API keys."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from agentjury import Panel, ReviewRequest, Verdict, adjudication
from agentjury.cli import main
from agentjury.judges import FakeJudge
from agentjury.protocol import ArtifactCoverage, HumanReview, LocalSignal, Producer

SENTINEL = "ZQX-SENTINEL-TEXT"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTJURY_VERDICT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def verdict(*judges, task_type="code_change", created_at=T0) -> Verdict:
    result = Panel(list(judges)).review(ReviewRequest(task="t", output="o", task_type=task_type))
    result.created_at = created_at
    return result


def save(directory, *verdicts):
    directory.mkdir(parents=True, exist_ok=True)
    for item in verdicts:
        (directory / item.filename).write_text(item.model_dump_json(indent=2), encoding="utf-8")
    return directory


def finding(text, severity, **evidence):
    item = {"text": text, "severity": severity}
    if evidence:
        item["evidence"] = {"output_quote": "o", "basis_source": "task", "basis_quote": "t", **evidence}
    return item


def test_pending_orders_contested_findings_first_and_numbers_them_for_adjudicate(workspace, capsys):
    overruled = verdict(FakeJudge("accuracy", provider="openai"), FakeJudge("evidence", provider="openai"),
                        FakeJudge("critic", provider="anthropic", vote="revise", score=4,
                                  findings=[finding("Minor nit", "minor"), finding("Fabricated figure", "major")]))
    decisive = verdict(FakeJudge("accuracy", provider="openai"),
                       FakeJudge("critic", provider="anthropic", vote="revise", score=2,
                                 findings=[finding("Wrong answer", "blocking")]),
                       FakeJudge("executive", provider="openai"), created_at=T0 - timedelta(days=1))
    quiet_new = verdict(FakeJudge("accuracy", provider="openai", findings=[finding("Style", "minor")]),
                        FakeJudge("critic", provider="anthropic"), created_at=T0 + timedelta(days=2))
    quiet_old = verdict(FakeJudge("accuracy", provider="openai", findings=[finding("Typo", "minor")]),
                        FakeJudge("critic", provider="anthropic"), created_at=T0 + timedelta(days=1))
    assert overruled.status == "verified" and decisive.status == "needs_revision"
    directory = save(workspace / ".agentjury" / "verdicts", overruled, decisive, quiet_new, quiet_old)

    assert main(["adjudication", "pending", "--json"]) == 0
    groups = json.loads(capsys.readouterr().out)["verdicts"]
    assert [g["run_id"] for g in groups] == [decisive.run_id, overruled.run_id, quiet_new.run_id, quiet_old.run_id]
    assert [f["contested"] for f in groups[0]["findings"]] == ["decided the outcome"]
    # A split vote makes every finding in that verdict contested; the overruled one ranks first.
    assert [(f["number"], f["contested"]) for f in groups[1]["findings"]] == [
        (2, "panel overruled this reviewer"), (1, "split vote")]
    assert groups[2]["findings"][0]["contested"] is None and groups[2]["producer_missing"]

    first = groups[1]["findings"][0]
    assert main(["adjudicate", overruled.run_id, "--dir", str(directory), "--judge", first["judge_ref"],
                 "--finding", str(first["number"]), "wrong"]) == 0
    graded = Verdict.model_validate_json((directory / overruled.filename).read_text(encoding="utf-8"))
    review = next(r for r in graded.reviews if r.judge == first["judge"])
    assert review.findings[1].adjudication == "wrong" and review.findings[1].id == first["finding_id"]
    assert review.findings[0].adjudication is None


def test_pending_text_output_commands_limit_and_escaping(workspace, capsys):
    split = verdict(FakeJudge("accuracy", provider="openai"),
                    FakeJudge("critic", provider="anthropic", vote="revise", score=4,
                              findings=[finding("Bad\x1b[31m", "minor")]))
    other = verdict(FakeJudge("accuracy", provider="openai", findings=[finding("Later", "minor")]),
                    FakeJudge("critic", provider="anthropic"), created_at=T0 + timedelta(days=1))
    directory = save(workspace / "my verdicts", split, other)

    assert main(["adjudication", "pending", "--dir", str(directory), "-n", "1"]) == 0
    shown = capsys.readouterr().out
    assert "Pending adjudication: 2 ungraded findings (1 contested) in 2 verdicts; 2 verdicts without a producer grade." in shown
    assert f"run {split.run_id}" in shown and f"run {other.run_id}" not in shown
    assert "1 more verdicts not shown" in shown
    assert "Bad\\x1b[31m  (split vote)" in shown and "\x1b" not in shown
    assert (f'agentjury adjudicate {split.run_id} --dir "{directory}" --judge critic/anthropic --finding 1 '
            "correct|partially_correct|wrong") in shown
    assert f'agentjury adjudicate {split.run_id} --dir "{directory}" --producer-verdict correct|flawed' in shown


def test_pending_uses_review_id_when_judge_names_collide(workspace, capsys):
    base = verdict(FakeJudge("accuracy", provider="openai", findings=[finding("One", "minor")]),
                   FakeJudge("critic", provider="anthropic"))
    twin = base.reviews[0].model_copy(update={"review_id": "twin00000000", "config_id": "other",
                                               "findings": [base.reviews[0].findings[0].model_copy(update={"id": "f2"})]})
    base.reviews.append(twin)
    directory = save(workspace / ".agentjury" / "verdicts", base)
    assert main(["adjudication", "pending", "--json"]) == 0
    [group] = json.loads(capsys.readouterr().out)["verdicts"]
    refs = {f["review_id"]: f["judge_ref"] for f in group["findings"]}
    assert refs == {base.reviews[0].review_id: base.reviews[0].review_id, "twin00000000": "twin00000000"}
    assert main(["adjudicate", base.run_id, "--dir", str(directory), "--judge", "twin00000000", "--finding", "1", "correct"]) == 0


def test_nothing_pending_and_missing_directory(workspace, capsys):
    assert main(["adjudication", "pending"]) == 0
    assert "Nothing pending." in capsys.readouterr().out
    done = verdict(FakeJudge("accuracy", provider="openai"), FakeJudge("critic", provider="anthropic"))
    done.human_verdict = "correct"
    save(workspace / ".agentjury" / "verdicts", done)
    assert main(["adjudication", "pending"]) == 0
    assert "0 ungraded findings (0 contested) in 0 verdicts; 0 verdicts" in capsys.readouterr().out


def crafted_verdict() -> Verdict:
    result = verdict(
        FakeJudge("accuracy", provider="openai", reason=SENTINEL, params={"route": "ollama", "custom_url": SENTINEL}),
        FakeJudge("critic", provider="anthropic", vote="revise", score=3, reason=SENTINEL,
                  findings=[finding(SENTINEL, "major", output_quote=SENTINEL, basis_quote=SENTINEL)]),
    )
    result.errors.append(f"executive/openai: RuntimeError: {SENTINEL}")
    result.local_signals.append(LocalSignal(rule_id="force_approval", excerpt=SENTINEL))
    result.producer = Producer(agent=SENTINEL, framework="claude-code", provider="anthropic", model="claude-x")
    result.artifact_coverage = [ArtifactCoverage(name=SENTINEL, coverage="full"),
                                ArtifactCoverage(name=SENTINEL + "2", coverage="omitted")]
    result.human_verdict, result.human_note = "flawed", SENTINEL
    result.reviews[1].human_review = HumanReview(verdict="disagree", note=SENTINEL)
    result.reviews[1].findings[0].adjudication = "wrong"
    result.pending_adjudication_events = [{"event_id": "pending1", "kind": "finding", "note": SENTINEL}]
    result.domain = "python"
    return result


def test_export_contains_grades_and_identities_but_no_text(workspace, capsys):
    item = crafted_verdict()
    directory = save(workspace / ".agentjury" / "verdicts", item)
    (directory / "adjudications.jsonl").write_text(json.dumps({
        "event_id": "evt1", "at": "2026-10-03T20:00:00+00:00", "adjudicator": SENTINEL, "run_id": item.run_id,
        "request_id": item.request_id, "note": SENTINEL, "kind": "finding", "review_id": item.reviews[1].review_id,
        "judge": "critic/anthropic", "config_id": item.reviews[1].config_id,
        "finding_id": item.reviews[1].findings[0].id, "old": None, "new": "wrong"}) + "\n", encoding="utf-8")

    assert main(["adjudication", "export", "--out", str(workspace / "export.json")]) == 0
    text = (workspace / "export.json").read_text(encoding="utf-8")
    assert SENTINEL not in text and "custom_url" not in text and "adjudicator" not in text
    document = json.loads(text)
    assert document["kind"] == "agentjury.adjudication.export" and document["version"] == 1
    assert document["counts"] == {"verdicts": 1, "reviews": 2, "findings": 1, "graded_findings": 1,
                                  "producer_grades": 1, "events": 1, "pending_events": 1,
                                  "unreadable": 0, "duplicates": 0}
    [exported] = document["verdicts"]
    assert exported["producer"] == {"framework": "claude-code", "provider": "anthropic", "model": "claude-x"}
    assert exported["artifact_coverage"] == {"full": 1, "omitted": 1}
    assert exported["local_signal_rules"] == ["force_approval"] and exported["error_count"] == 1
    assert exported["human_verdict"] == "flawed" and exported["domain"] == "python"
    accuracy, critic = exported["reviews"]
    assert accuracy["params"] == {"route": "ollama", "timeout": 5.0}
    assert critic["human_review"] == {"verdict": "disagree", "reviewed_at": critic["human_review"]["reviewed_at"]}
    assert critic["findings"] == [{"id": item.reviews[1].findings[0].id, "severity": "major", "has_evidence": True,
                                   "basis_source": "task", "adjudication": "wrong",
                                   "adjudicated_at": critic["findings"][0]["adjudicated_at"]}]
    assert set(critic) >= {"config_id", "prompt_hash", "rubric_version", "vote", "score", "latency_ms"}
    [event] = document["events"]
    assert event == {"event_id": "evt1", "at": "2026-10-03T20:00:00+00:00", "kind": "finding", "run_id": item.run_id,
                     "request_id": item.request_id, "review_id": item.reviews[1].review_id,
                     "config_id": item.reviews[1].config_id, "judge": "critic/anthropic",
                     "finding_id": item.reviews[1].findings[0].id, "old": None, "new": "wrong"}
    assert "No reviewed text" in capsys.readouterr().out


def test_export_to_stdout_reads_several_directories_and_skips_bad_records(workspace, capsys):
    item = crafted_verdict()
    first = save(workspace / "a", item)
    second = save(workspace / "b", item)
    (first / "broken.json").write_text("{not json", encoding="utf-8")
    event = json.dumps({"event_id": "evt1", "kind": "producer", "run_id": item.run_id, "old": None, "new": "flawed"})
    (first / "adjudications.jsonl").write_text(event + "\nnot json\n", encoding="utf-8")
    (second / "adjudications.jsonl").write_text(event + "\n" + json.dumps({"no": "id"}) + "\n", encoding="utf-8")

    assert main(["adjudication", "export", "--dir", str(first), "--dir", str(second)]) == 0
    out, err = capsys.readouterr()
    document = json.loads(out)
    assert document["counts"]["verdicts"] == 1 and document["counts"]["events"] == 1
    assert document["counts"]["unreadable"] == 3 and document["counts"]["duplicates"] == 2
    assert SENTINEL not in out and "3 unreadable and 2 duplicate" in err


def test_stats_count_grades_per_configuration_and_agree_with_export(workspace, capsys):
    flawed = crafted_verdict()
    # Same parameters as the crafted accuracy judge, so both reviews share one configuration ID.
    correct = verdict(FakeJudge("accuracy", provider="openai", vote="revise", score=4,
                                params={"route": "ollama", "custom_url": SENTINEL},
                                findings=[finding("Wrong claim", "major")]),
                      FakeJudge("critic", provider="anthropic"),
                      FakeJudge("executive", provider="openai", vote="abstain", score=5), task_type="summary")
    correct.human_verdict = "correct"
    correct.reviews[0].findings[0].adjudication = "correct"
    correct.reviews[0].human_review = HumanReview(verdict="agree")
    directory = save(workspace / ".agentjury" / "verdicts", flawed, correct)

    assert main(["adjudication", "stats", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["verdicts"], result["producer_grades"], result["graded_findings"]) == (2, 2, 2)
    assert result["jury_status_vs_producer_grade"] == {"needs_revision:correct": 1, "needs_revision:flawed": 1}
    assert len(result["configurations"]) == 3
    by_judge = {c["judge"]: c for c in result["configurations"]}
    accuracy = by_judge["accuracy/openai"]["all"]
    assert (accuracy["reviews"], accuracy["on_graded_outputs"]) == (2, 2)
    assert (accuracy["false_approvals"], accuracy["false_rejections"], accuracy["agreements"]) == (1, 1, 0)
    assert (accuracy["graded"], accuracy["correct"], accuracy["agree"]) == (1, 1, 1)
    assert set(by_judge["accuracy/openai"]["task_types"]) == {"code_change", "summary"}
    critic = by_judge["critic/anthropic"]["all"]
    # The critic revised the flawed output and approved the correct one: two agreements.
    assert (critic["wrong"], critic["disagree"], critic["agreements"], critic["false_rejections"]) == (1, 1, 2, 0)
    executive = by_judge["executive/openai"]["all"]
    assert executive["on_graded_outputs"] == 0 and executive["reviews"] == 1
    assert "not reputation weights" in result["disclaimer"]

    assert main(["adjudication", "export", "--out", str(workspace / "export.json")]) == 0
    capsys.readouterr()
    assert main(["adjudication", "stats", "--from", str(workspace / "export.json"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == result

    assert main(["adjudication", "stats", "--dir", str(directory)]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("Adjudication stats: 2 graded findings in 2 verdicts (2 with a producer grade).")
    assert adjudication.DISCLAIMER in shown and SENTINEL not in shown
    assert "needs_revision with flawed 1" in shown and "false approvals 1" in shown


def test_stats_rejects_other_files(workspace, capsys):
    (workspace / "other.json").write_text('{"kind": "something"}', encoding="utf-8")
    assert main(["adjudication", "stats", "--from", str(workspace / "other.json")]) == 1
    assert "Not an AgentJury adjudication export" in capsys.readouterr().err
    assert main(["adjudication", "stats", "--from", str(workspace / "missing.json")]) == 1
    assert main(["adjudication", "stats"]) == 0
    assert "No reviews found." in capsys.readouterr().out


def test_old_verdicts_without_new_fields_still_load(workspace, capsys):
    old = verdict(FakeJudge("accuracy", provider="openai", findings=[finding("x", "minor")]),
                  FakeJudge("critic", provider="anthropic")).model_dump(mode="json")
    for key in ("local_signals", "local_guard_applied", "artifact_coverage", "pending_adjudication_events"):
        del old[key]
    old["schema_version"] = "0.5"
    del old["reviews"][0]["findings"][0]["evidence"]
    directory = workspace / ".agentjury" / "verdicts"
    directory.mkdir(parents=True)
    (directory / "old.json").write_text(json.dumps(old), encoding="utf-8")
    assert main(["adjudication", "pending"]) == 0
    assert "1 ungraded findings" in capsys.readouterr().out
    assert main(["adjudication", "export"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["verdicts"][0]["schema_version"] == "0.5"
    assert document["verdicts"][0]["reviews"][0]["findings"][0]["has_evidence"] is False
