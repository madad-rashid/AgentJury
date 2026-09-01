"""Tests for the aggregator and panel. No API keys needed: uses FakeJudge."""

import pytest

from agentjury import Panel, ReviewRequest, aggregate
from agentjury.judges import FakeJudge

REQ = ReviewRequest(task="Write a haiku about rain.", output="Rain taps the window...")


def run(*judges):
    return Panel(list(judges)).review(REQ)


def test_unanimous_approval_is_verified():
    v = run(FakeJudge("accuracy", score=9), FakeJudge("critic", score=8), FakeJudge("executive", score=9))
    assert v.up == 3 and v.down == 0
    assert v.status == "verified"
    assert v.consensus == 1.0
    assert v.score == pytest.approx(8.67, abs=0.01)


def test_majority_approve_is_verified():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=5), FakeJudge("executive"))
    assert v.up == 2 and v.down == 1
    assert v.status == "verified"
    assert v.consensus == pytest.approx(2 / 3, abs=0.01)


def test_tie_needs_revision():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=4))
    assert v.status == "needs_revision"


def test_blocking_issue_overrides_majority():
    v = run(
        FakeJudge("accuracy"),
        FakeJudge("executive"),
        FakeJudge("critic", vote="revise", score=3, issues=["Fabricated source"], blocking=True),
    )
    assert v.up == 2
    assert v.status == "blocked"


def test_confidence_falls_with_disagreement():
    agree = run(FakeJudge("accuracy", score=8), FakeJudge("critic", score=8), FakeJudge("executive", score=8))
    disagree = run(FakeJudge("accuracy", score=10), FakeJudge("critic", score=2), FakeJudge("executive", score=8))
    assert agree.confidence > disagree.confidence


def test_bigger_panel_is_more_confident():
    small = run(FakeJudge("accuracy"), FakeJudge("critic"), FakeJudge("executive"))
    big = run(*[FakeJudge(r) for r in ["accuracy", "critic", "executive", "evidence", "accuracy"]])
    assert big.confidence > small.confidence


def test_failed_judge_is_recorded_not_fatal():
    class Broken(FakeJudge):
        def complete(self, system, user):
            raise ConnectionError("simulated outage")

    v = run(FakeJudge("accuracy"), Broken("critic"), FakeJudge("executive"))
    assert v.up == 2 and v.down == 0
    assert len(v.errors) == 1
    assert "critic/fake" in v.errors[0]


def test_aggregate_rejects_empty():
    with pytest.raises(ValueError):
        aggregate("x", [])


def test_render_is_one_line():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=6))
    assert "\n" not in v.render()
    assert "▲1" in v.render() and "▼1" in v.render()
