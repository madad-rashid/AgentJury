"""The adjudicate and verdicts CLI commands, against a saved verdict from FakeJudges."""

import json

import pytest

from agentjury import Panel, ReviewRequest, Verdict
from agentjury.cli import main
from agentjury.judges import FakeJudge


@pytest.fixture
def saved(tmp_path):
    v = Panel([
        FakeJudge("accuracy", provider="openai", score=9),
        FakeJudge("critic", provider="anthropic", vote="revise", score=5, findings=[
            {"text": "Figure looks fabricated", "severity": "major"},
            {"text": "BDC claim uncited", "severity": "minor"},
            {"text": "Over word count", "severity": "minor"},
        ]),
    ]).review(ReviewRequest(task="t", output="o"))
    d = tmp_path / "verdicts"
    d.mkdir()
    f = d / f"{v.request_id}.json"
    f.write_text(v.model_dump_json(indent=2), encoding="utf-8")
    return d, v


def reload(d, v):
    return Verdict.model_validate_json((d / f"{v.request_id}.json").read_text(encoding="utf-8"))


def test_adjudicate_findings_and_review(saved, capsys):
    d, v = saved
    rc = main(["adjudicate", v.request_id, "--dir", str(d), "--judge", "critic/anthropic",
               "--finding", "1", "wrong", "--finding", "2", "wrong", "--finding", "3", "correct",
               "--verdict", "disagree", "--note", "figure is in the BIS source"])
    assert rc == 0
    v2 = reload(d, v)
    critic = next(r for r in v2.reviews if r.role == "critic")
    assert [f.adjudication for f in critic.findings] == ["wrong", "wrong", "correct"]
    assert all(f.adjudicated_at for f in critic.findings)
    assert critic.human_review.verdict == "disagree" and "BIS" in critic.human_review.note
    accuracy = next(r for r in v2.reviews if r.role == "accuracy")
    assert accuracy.human_review is None  # untouched
    assert v2.human_verdict is None


def test_adjudicate_producer(saved):
    d, v = saved
    main(["adjudicate", v.request_id, "--dir", str(d), "--producer-verdict", "correct", "--note", "checked source"])
    v2 = reload(d, v)
    assert v2.human_verdict == "correct" and v2.human_note == "checked source" and v2.adjudicated_at


def test_adjudicate_by_prefix_and_by_role(saved):
    d, v = saved
    main(["adjudicate", v.request_id[:6], "--dir", str(d), "--judge", "critic", "--finding", "1", "wrong"])
    assert reload(d, v).reviews[1].findings[0].adjudication == "wrong"


def test_adjudicate_by_finding_id(saved):
    d, v = saved
    fid = v.reviews[1].findings[2].id
    main(["adjudicate", v.request_id, "--dir", str(d), "--judge", "critic", "--finding", fid, "correct"])
    assert reload(d, v).reviews[1].findings[2].adjudication == "correct"


def test_adjudicate_uses_env_dir(saved, monkeypatch):
    d, v = saved
    monkeypatch.setenv("AGENTJURY_VERDICT_DIR", str(d))
    main(["adjudicate", v.request_id, "--producer-verdict", "flawed"])
    assert reload(d, v).human_verdict == "flawed"


@pytest.mark.parametrize("argv,msg", [
    (["--judge", "critic", "--finding", "9", "wrong"], "no finding"),
    (["--judge", "critic", "--finding", "1", "maybe"], "Finding label"),
    (["--judge", "nobody", "--finding", "1", "wrong"], "matched 0"),
    (["--finding", "1", "wrong"], "--judge is required"),
    ([], "Nothing to record"),
])
def test_adjudicate_rejects_bad_input(saved, argv, msg):
    d, v = saved
    with pytest.raises(SystemExit) as e:
        main(["adjudicate", v.request_id, "--dir", str(d), *argv])
    assert msg in str(e.value)


def test_unknown_id_fails_clearly(saved):
    d, _ = saved
    with pytest.raises(SystemExit) as e:
        main(["adjudicate", "zzzz", "--dir", str(d), "--producer-verdict", "correct"])
    assert "Cannot find verdict" in str(e.value)


def test_verdicts_lists_and_marks_adjudicated(saved, capsys):
    d, v = saved
    main(["verdicts", "--dir", str(d)])
    out = capsys.readouterr().out
    assert v.request_id in out and "adjudicated" not in out
    main(["adjudicate", v.request_id, "--dir", str(d), "--judge", "critic", "--finding", "1", "wrong",
          "--producer-verdict", "correct"])
    main(["verdicts", "--dir", str(d)])
    out = capsys.readouterr().out
    assert "[adjudicated 1/3]" in out and "producer:correct" in out
