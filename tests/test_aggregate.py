"""Tests for the aggregator and panel. No API keys needed: uses FakeJudge."""

import pytest

from agentjury import Panel, ReviewRequest, aggregate
from agentjury.judges import FakeJudge

REQ = ReviewRequest(task="Write a haiku about rain.", output="Rain taps the window...")


def run(*judges):
    return Panel(list(judges)).review(REQ)


def mixed(*roles):
    """Three judges from three different providers."""
    providers = ["openai", "anthropic", "google"]
    return [FakeJudge(r, provider=providers[i % 3]) for i, r in enumerate(roles)]


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


def test_blocking_finding_overrides_majority():
    v = run(
        FakeJudge("accuracy"),
        FakeJudge("executive"),
        FakeJudge("critic", vote="revise", score=3,
                  findings=[{"text": "Fabricated source", "severity": "blocking"}]),
    )
    assert v.up == 2
    assert v.status == "blocked"
    assert v.reviews[2].blocking is True


def test_major_finding_does_not_block():
    v = run(FakeJudge("accuracy", findings=[{"text": "Weak source", "severity": "major"}]))
    assert v.status == "verified"
    assert v.reviews[0].blocking is False


def test_confidence_falls_with_disagreement():
    agree = run(FakeJudge("accuracy", score=8), FakeJudge("critic", score=8), FakeJudge("executive", score=8))
    disagree = run(FakeJudge("accuracy", score=10), FakeJudge("critic", score=2), FakeJudge("executive", score=8))
    assert agree.confidence > disagree.confidence


def test_bigger_panel_is_more_confident_at_equal_diversity():
    small = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate(["accuracy", "critic", "executive"])])
    big = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate(["accuracy", "critic", "executive", "evidence", "accuracy"])])
    assert small.diversity == big.diversity == 1.0
    assert big.confidence > small.confidence


def test_three_families_beat_five_clones():
    """A 3-0 from three providers deserves more trust than a 5-0 from one."""
    clones = run(*[FakeJudge(r) for r in ["accuracy", "critic", "executive", "evidence", "accuracy"]])
    families = run(*mixed("accuracy", "critic", "executive"))
    assert clones.up == 5 and families.up == 3
    assert families.confidence > clones.confidence


def test_diversity_measures_distinct_providers():
    same = run(FakeJudge("accuracy"), FakeJudge("critic"), FakeJudge("executive"))
    varied = run(*mixed("accuracy", "critic", "executive"))
    assert same.diversity == pytest.approx(1 / 3, abs=0.01)
    assert varied.diversity == 1.0
    assert varied.confidence > same.confidence


def test_failed_judge_is_recorded_not_fatal():
    class Broken(FakeJudge):
        def complete(self, system, user):
            raise ConnectionError("simulated outage")

    v = run(FakeJudge("accuracy"), Broken("critic"), FakeJudge("executive"))
    assert v.up == 2 and v.down == 0
    assert len(v.errors) == 1
    assert "critic/fake" in v.errors[0]


def test_review_carries_telemetry():
    v = run(FakeJudge("critic", findings=[{"text": "x"}]))
    r = v.reviews[0]
    assert r.role == "critic" and r.provider == "fake" and r.model == "fake-1"
    assert r.rubric_version == "0.1"
    assert len(r.prompt_hash) == 12
    assert r.latency_ms is not None and r.latency_ms >= 0
    assert r.tokens_in == 100 and r.tokens_out == 50
    assert r.self_confidence == 0.8
    assert r.findings[0].adjudication is None
    assert r.human_review is None


def test_verdict_carries_request_metadata():
    req = ReviewRequest(task="t", output="o", task_type="summary", domain="finance")
    req.producer.model = "gpt-5.6"
    v = Panel([FakeJudge("accuracy")]).review(req)
    assert v.task_type == "summary" and v.domain == "finance"
    assert v.producer.model == "gpt-5.6"
    assert v.schema_version == "0.1"


def test_aggregate_rejects_empty():
    with pytest.raises(ValueError):
        aggregate(REQ, [])


def test_render_is_one_line():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=6))
    assert "\n" not in v.render()
    assert "▲1" in v.render() and "▼1" in v.render()
