"""Pending findings, the text-free export and descriptive stats, on crafted verdicts. No API keys."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentjury import Panel, ReviewRequest, Verdict, adjudication
from agentjury.cli import main
from agentjury.judges import FakeJudge
from agentjury.local_store import verdict_dirs
from agentjury.protocol import ArtifactCoverage, HumanReview, LocalSignal, Producer

SENTINEL = "ZQX-SENTINEL-TEXT"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


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


def approve(role, provider, **kw):
    return FakeJudge(role, provider=provider, **kw)


def revise(role, provider, findings, score=4):
    return FakeJudge(role, provider=provider, vote="revise", score=score, findings=findings)


def test_pending_orders_by_disagreement_and_numbers_findings_as_saved(workspace, capsys):
    overruled = verdict(approve("accuracy", "openai"), approve("evidence", "openai"),
                        revise("critic", "anthropic", [finding("Minor nit", "minor"), finding("Fabricated figure", "major")]))
    decisive = verdict(approve("accuracy", "openai"), revise("critic", "anthropic", [finding("Wrong answer", "blocking")], 2),
                       approve("executive", "openai"), created_at=T0 - timedelta(days=1))
    quiet_new = verdict(approve("accuracy", "openai", findings=[finding("Style", "minor")]),
                        approve("critic", "anthropic"), created_at=T0 + timedelta(days=2))
    quiet_old = verdict(approve("accuracy", "openai", findings=[finding("Typo", "minor")]),
                        approve("critic", "anthropic"), created_at=T0 + timedelta(days=1))
    assert overruled.status == "verified" and decisive.status == "needs_revision"
    directory = save(workspace / ".agentjury" / "verdicts", overruled, decisive, quiet_new, quiet_old)

    assert main(["adjudication", "pending", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"ungraded_findings": 5, "contested_findings": 3, "verdicts_with_ungraded_findings": 4,
                                 "verdicts_without_producer_grade": 4, "reviews_without_grade": 10}
    groups = payload["findings"]
    assert [g["run_id"] for g in groups] == [decisive.run_id, overruled.run_id, quiet_new.run_id, quiet_old.run_id]
    assert [f["contested"] for f in groups[0]["findings"]] == ["blocking finding changed the outcome"]
    # Saved order is kept; the dissenting reviewer's findings are marked, not reordered.
    assert [(f["number"], f["contested"]) for f in groups[1]["findings"]] == [
        (1, "voted revise; the panel verified"), (2, "voted revise; the panel verified")]
    assert groups[2]["findings"][0]["contested"] is None
    assert [g["run_id"] for g in payload["producer"]] == [quiet_new.run_id, quiet_old.run_id, overruled.run_id, decisive.run_id]

    second = groups[1]["findings"][1]
    assert main(["adjudicate", overruled.run_id, "--dir", str(directory), "--judge", second["judge_ref"],
                 "--finding", str(second["number"]), "wrong"]) == 0
    graded = Verdict.model_validate_json((directory / overruled.filename).read_text(encoding="utf-8"))
    review = next(r for r in graded.reviews if r.judge == second["judge"])
    assert review.findings[1].adjudication == "wrong" and review.findings[1].id == second["finding_id"]
    assert review.findings[0].adjudication is None

    # A graded finding keeps its number; the remaining one is still printed as finding 1.
    assert main(["adjudication", "pending"]) == 0
    shown = capsys.readouterr().out
    assert "critic/anthropic  finding 1  [minor]  Minor nit" in shown and "finding 2  [major]" not in shown


def test_pending_text_output_commands_limit_and_escaping(workspace, capsys):
    split = verdict(approve("accuracy", "openai"), approve("executive", "openai"),
                    revise("critic", "anthropic", [finding("Bad\x1b[31m", "minor")]))
    other = verdict(approve("accuracy", "openai", findings=[finding("Later", "minor")]),
                    approve("critic", "anthropic"), created_at=T0 + timedelta(days=1))
    other.pending_adjudication_events = [{"event_id": "p1", "kind": "producer"}]
    directory = save(workspace / "my verdicts", split, other)

    assert main(["adjudication", "pending", "--dir", str(directory), "-n", "1"]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("Pending adjudication: 2 ungraded findings (1 contested) in 2 verdicts; "
                            "2 verdicts without a producer grade; 5 reviews without an overall grade.")
    assert "1 more verdicts with ungraded findings not shown" in shown
    assert "1 more verdicts without a producer grade not shown" in shown
    assert "Bad\\x1b[31m  (voted revise; the panel verified)" in shown and "\x1b" not in shown
    assert (f'agentjury adjudicate {split.run_id} --dir "{directory}" --judge critic/anthropic --finding 1 '
            "correct|partially_correct|wrong") in shown
    assert f'agentjury adjudicate {other.run_id} --dir "{directory}" --producer-verdict correct|flawed' in shown
    assert f'agentjury adjudicate {other.run_id} --dir "{directory}" --judge accuracy/openai --verdict agree|partial|disagree' in shown
    assert "reviews without an overall grade: accuracy/openai, critic/anthropic" in shown
    assert "1 adjudication events not yet in adjudications.jsonl" in shown
    assert "confidence" in shown and "[contested]" in shown


def test_pending_reads_several_directories_and_names_each_verdicts_own(workspace, capsys):
    first = save(workspace / "hermes", verdict(approve("accuracy", "openai"),
                                               revise("critic", "anthropic", [finding("A", "minor")])))
    second = save(workspace / "repo", verdict(approve("accuracy", "openai"),
                                              revise("critic", "anthropic", [finding("B", "minor")]), created_at=T0 + timedelta(days=1)))
    assert main(["adjudication", "pending", "--dir", str(first), "--dir", str(second), "--dir", str(first)]) == 0
    shown = capsys.readouterr().out
    assert f"--dir {second} --judge critic/anthropic" in shown and f"--dir {first} --judge critic/anthropic" in shown
    assert "Skipped" not in shown
    assert verdict_dirs([str(first), str(first), str(second)]) == [first, second]


def test_pending_uses_review_id_when_judge_names_collide(workspace, capsys):
    base = verdict(approve("accuracy", "openai", findings=[finding("One", "minor")]), approve("critic", "anthropic"))
    twin = base.reviews[0].model_copy(update={"review_id": "twin00000000", "config_id": "other",
                                               "findings": [base.reviews[0].findings[0].model_copy(update={"id": "f2"})]})
    base.reviews.append(twin)
    directory = save(workspace / ".agentjury" / "verdicts", base)
    assert main(["adjudication", "pending", "--json"]) == 0
    [group] = json.loads(capsys.readouterr().out)["findings"]
    refs = {f["review_id"]: f["judge_ref"] for f in group["findings"]}
    assert refs == {base.reviews[0].review_id: base.reviews[0].review_id, "twin00000000": "twin00000000"}
    assert main(["adjudicate", base.run_id, "--dir", str(directory), "--judge", "twin00000000", "--finding", "1", "correct"]) == 0


def test_insufficient_jury_findings_are_contested_only_on_a_split(workspace, capsys):
    # Four requested, quorum three, two failed: the two votes split and no verdict is reached.
    split = verdict(approve("accuracy", "openai"), revise("critic", "anthropic", [finding("X", "minor")]),
                    FakeJudge("executive", provider="openai", fail_times=5),
                    FakeJudge("evidence", provider="anthropic", fail_times=5))
    assert split.status == "insufficient_jury"
    save(workspace / ".agentjury" / "verdicts", split)
    assert main(["adjudication", "pending", "--json"]) == 0
    [group] = json.loads(capsys.readouterr().out)["findings"]
    assert group["findings"][0]["contested"] == "split vote, no verdict" and group["status"] == "insufficient_jury"


def test_nothing_pending(workspace, capsys):
    assert main(["adjudication", "pending"]) == 0
    assert "Nothing pending." in capsys.readouterr().out
    done = verdict(approve("accuracy", "openai"), approve("critic", "anthropic"))
    done.human_verdict = "correct"
    save(workspace / ".agentjury" / "verdicts", done)
    assert main(["adjudication", "pending"]) == 0
    assert "0 ungraded findings (0 contested) in 0 verdicts; 0 verdicts without a producer grade; 0 reviews" in capsys.readouterr().out


def crafted_verdict() -> Verdict:
    result = verdict(
        FakeJudge("accuracy", provider="openai", reason=SENTINEL,
                  params={"route": "ollama", "custom_url": SENTINEL, "effort": SENTINEL}),
        FakeJudge("critic", provider="anthropic", vote="revise", score=3, reason=SENTINEL,
                  findings=[finding(SENTINEL, "major", output_quote=SENTINEL, basis_quote=SENTINEL)]),
    )
    result.errors.append(f"executive/openai: RuntimeError: {SENTINEL}")
    result.errors.append(f"{SENTINEL} broke: {SENTINEL}")
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
    assert adjudication.audit_export(document) == []
    assert document["kind"] == "agentjury.adjudication.export" and document["version"] == 1
    assert document["counts"] == {"verdicts": 1, "reviews": 2, "findings": 1, "graded_findings": 1, "graded_reviews": 1,
                                  "producer_grades": 1, "events": 1, "orphan_events": 0, "pending_events": 1,
                                  "params_dropped": 2, "unreadable": 0, "duplicates": 0}
    [exported] = document["verdicts"]
    assert exported["producer"] == {"framework": "claude-code", "provider": "anthropic", "model": "claude-x"}
    assert exported["artifact_coverage"] == {"full": 1, "omitted": 1}
    assert exported["local_signal_rules"] == ["force_approval"] and exported["error_count"] == 2
    assert exported["errors"] == [{"judge": "executive/openai", "error": "RuntimeError"}, {"judge": None, "error": None}]
    assert exported["human_verdict"] == "flawed" and exported["domain"] == "python"
    accuracy, critic = exported["reviews"]
    assert accuracy["params"] == {"route": "ollama", "timeout": 5.0}
    assert critic["human_review"] == {"verdict": "disagree", "reviewed_at": critic["human_review"]["reviewed_at"]}
    assert critic["findings"] == [{"id": item.reviews[1].findings[0].id, "severity": "major", "has_evidence": True,
                                   "basis_source": "task", "adjudication": "wrong",
                                   "adjudicated_at": critic["findings"][0]["adjudicated_at"]}]
    assert set(critic) >= {"config_id", "prompt_hash", "rubric_version", "vote", "score", "latency_ms", "created_at"}
    [event] = document["events"]
    assert event == {"event_id": "evt1", "at": "2026-10-03T20:00:00+00:00", "kind": "finding", "run_id": item.run_id,
                     "request_id": item.request_id, "review_id": item.reviews[1].review_id,
                     "config_id": item.reviews[1].config_id, "judge": "critic/anthropic",
                     "finding_id": item.reviews[1].findings[0].id, "old": None, "new": "wrong"}
    summary = capsys.readouterr().out
    assert "No reviewed text" in summary and "2 reviewer parameters outside the allowlist" in summary
    assert "judge: accuracy/openai, critic/anthropic, executive/openai" in summary
    assert "model: claude-x, fake-1" in summary and SENTINEL not in summary


def test_export_audit_catches_strings_outside_the_allowlist():
    document = {"kind": adjudication.EXPORT_KIND, "verdicts": [{"run_id": "abc", "status": "verified",
                                                                "note": "free text", "reviews": [{"vote": "maybe"}]}]}
    assert adjudication.audit_export(document) == ["verdicts/*/note", "verdicts/*/reviews/*/vote"]
    assert adjudication.free_text_values({"verdicts": [{"task_type": "code_change", "domain": "python"}]}) == {
        "domain": ["python"], "task_type": ["code_change"]}


def test_export_refuses_a_value_off_its_shape(workspace, capsys):
    item = crafted_verdict()
    item.run_id = "has space"
    save(workspace / ".agentjury" / "verdicts", item)
    assert main(["adjudication", "export"]) == 5
    out, err = capsys.readouterr()
    assert out == "" and "Export refused" in err and "verdicts/*/run_id" in err and "has space" not in err


def test_export_to_stdout_reads_several_directories_and_skips_bad_records(workspace, capsys):
    item = crafted_verdict()
    first = save(workspace / "a", item)
    second = save(workspace / "b", item)
    (first / "broken.json").write_text("{not json", encoding="utf-8")
    event = json.dumps({"event_id": "evt1", "kind": "producer", "run_id": item.run_id, "old": None, "new": "flawed"})
    orphan = json.dumps({"event_id": "evt2", "kind": "producer", "run_id": "nowhere00000", "old": None, "new": "correct"})
    (first / "adjudications.jsonl").write_text(event + "\nnot json\n", encoding="utf-8")
    (second / "adjudications.jsonl").write_text(event + "\n" + orphan + "\n" + json.dumps({"no": "id"}) + "\n", encoding="utf-8")

    assert main(["adjudication", "export", "--dir", str(first), "--dir", str(second)]) == 0
    out, err = capsys.readouterr()
    document = json.loads(out)
    assert document["counts"]["verdicts"] == 1 and document["counts"]["events"] == 2
    assert document["counts"]["orphan_events"] == 1
    assert document["counts"]["unreadable"] == 3 and document["counts"]["duplicates"] == 2
    assert SENTINEL not in out and "3 unreadable and 2 duplicate" in err and "1 for verdicts not read" in err


def test_duplicate_verdicts_keep_the_more_graded_copy(workspace, capsys):
    item = verdict(approve("accuracy", "openai"), revise("critic", "anthropic", [finding("A", "minor")]))
    first = save(workspace / "a", item)
    graded = item.model_copy(deep=True)
    graded.reviews[1].findings[0].adjudication = "correct"
    graded.reviews[1].findings[0].adjudicated_at = T0
    second = save(workspace / "b", graded)
    for order in ([first, second], [second, first]):
        assert main(["adjudication", "export", "--dir", str(order[0]), "--dir", str(order[1])]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["counts"]["graded_findings"] == 1 and document["counts"]["duplicates"] == 1


def test_stats_count_grades_per_configuration_and_agree_with_export(workspace, capsys):
    flawed = crafted_verdict()
    # Same parameters as the crafted accuracy judge, so both reviews share one configuration ID.
    correct = verdict(FakeJudge("accuracy", provider="openai", vote="revise", score=4,
                                params={"route": "ollama", "custom_url": SENTINEL, "effort": SENTINEL},
                                findings=[finding("Wrong claim", "major")]),
                      approve("critic", "anthropic"),
                      FakeJudge("executive", provider="openai", vote="abstain", score=5), task_type="summary")
    correct.human_verdict = "correct"
    correct.reviews[0].findings[0].adjudication = "correct"
    correct.reviews[0].human_review = HumanReview(verdict="agree")
    directory = save(workspace / ".agentjury" / "verdicts", flawed, correct)

    assert main(["adjudication", "stats", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["descriptive_only"] is True and "not reputation weights" in result["disclaimer"]
    assert (result["verdicts"], result["producer_grades"], result["graded_findings"]) == (2, 2, 2)
    assert result["jury_vs_producer_grade"] == {"graded": 2, "unsafe_approvals": 0, "false_rejections": 1,
                                                "agreements": 1, "unavailable": 0, "local_interventions": 0}
    assert result["status_with_producer_grade"] == {"needs_revision with correct": 1, "needs_revision with flawed": 1}
    assert len(result["configurations"]) == 3
    by_judge = {c["judge"]: c for c in result["configurations"]}
    accuracy = by_judge["accuracy/openai"]
    assert accuracy["params"] == {"timeout": 5.0} and len(accuracy["prompt_hash"]) == 12
    assert (accuracy["all"]["reviews"], accuracy["all"]["on_graded_outputs"]) == (2, 2)
    assert (accuracy["all"]["false_approvals"], accuracy["all"]["false_rejections"], accuracy["all"]["agreements"]) == (1, 1, 0)
    assert (accuracy["all"]["graded"], accuracy["all"]["correct"], accuracy["all"]["agree"]) == (1, 1, 1)
    assert set(accuracy["task_types"]) == {"code_change", "summary"}
    critic = by_judge["critic/anthropic"]["all"]
    # The critic revised the flawed output and approved the correct one: two agreements.
    assert (critic["wrong"], critic["disagree"], critic["agreements"], critic["false_rejections"]) == (1, 1, 2, 0)
    executive = by_judge["executive/openai"]["all"]
    assert (executive["on_graded_outputs"], executive["reviews"], executive["abstained"]) == (0, 1, 1)

    assert main(["adjudication", "export", "--out", str(workspace / "export.json")]) == 0
    capsys.readouterr()
    assert main(["adjudication", "stats", "--from", str(workspace / "export.json"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == result

    assert main(["adjudication", "stats", "--dir", str(directory)]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith("Adjudication stats: 2 graded findings in 2 verdicts (2 with a producer grade).")
    assert adjudication.DISCLAIMER in shown and SENTINEL not in shown
    assert "unsafe approvals 0, false rejections 1, agreements 1" in shown and "needs_revision with flawed 1" in shown
    assert "(timeout 5.0)" in shown and "1 abstained" in shown


def test_stats_rejects_other_files(workspace, capsys):
    (workspace / "other.json").write_text('{"kind": "something"}', encoding="utf-8")
    assert main(["adjudication", "stats", "--from", str(workspace / "other.json")]) == 5
    assert "Not an AgentJury adjudication export" in capsys.readouterr().err
    assert main(["adjudication", "stats", "--from", str(workspace / "missing.json")]) == 5
    assert main(["adjudication", "stats"]) == 0
    assert "No reviews found." in capsys.readouterr().out


def test_old_verdicts_without_new_fields_still_load(workspace, capsys):
    old = verdict(approve("accuracy", "openai", findings=[finding("x", "minor")]), approve("critic", "anthropic")).model_dump(mode="json")
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


def test_aggregation_never_reads_grades():
    for name in ("aggregate.py", "panel.py", "judges/base.py"):
        source = (ROOT / "agentjury" / name).read_text(encoding="utf-8")
        assert "adjudication" not in source.lower() or name == "judges/base.py" and "adjudications.jsonl" not in source
        assert "adjudications.jsonl" not in source and "human_verdict" not in source
