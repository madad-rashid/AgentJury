"""Tests for the aggregator and panel. No API keys needed: uses FakeJudge."""

import pytest

from agentjury import Panel, ReviewRequest, aggregate
from agentjury.judges import FakeJudge

REQ = ReviewRequest(task="Write a haiku about rain.", output="Rain taps the window...")
BLOCK = [{"text": "Fabricated source", "severity": "blocking"}]


def run(*judges, quorum=None):
    return Panel(list(judges), quorum=quorum).review(REQ)


def mixed(*roles, **kw):
    """Judges from rotating distinct providers."""
    providers = ["openai", "anthropic", "google"]
    return [FakeJudge(r, provider=providers[i % 3], **kw) for i, r in enumerate(roles)]


class Broken(FakeJudge):
    def complete(self, system, user):
        raise ConnectionError("simulated outage")


# --- votes -----------------------------------------------------------------

def test_unanimous_approval_is_verified():
    v = run(FakeJudge("accuracy", score=9), FakeJudge("critic", score=8), FakeJudge("executive", score=9))
    assert v.up == 3 and v.down == 0 and v.status == "verified" and v.consensus == 1.0
    assert v.score == pytest.approx(8.67, abs=0.01)


def test_majority_approve_is_verified():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=5), FakeJudge("executive"))
    assert v.up == 2 and v.down == 1 and v.status == "verified"


def test_tie_needs_revision():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=4))
    assert v.status == "needs_revision"


# --- blocking: no single judge can veto ------------------------------------

def test_one_blocking_judge_cannot_block_alone():
    v = run(*mixed("accuracy", "executive"), FakeJudge("critic", provider="google", vote="revise", score=3, findings=BLOCK))
    assert v.up == 2
    assert v.status == "needs_revision"  # downgraded from verified, but not blocked


def test_blocking_from_two_providers_blocks():
    v = run(
        FakeJudge("accuracy", provider="openai"),
        FakeJudge("critic", provider="anthropic", vote="revise", score=2, findings=BLOCK),
        FakeJudge("evidence", provider="google", vote="revise", score=3, findings=BLOCK),
    )
    assert v.status == "blocked"


def test_two_blocks_from_same_provider_do_not_block_in_mixed_panel():
    v = run(
        FakeJudge("accuracy", provider="openai"),
        FakeJudge("critic", provider="anthropic", vote="revise", score=2, findings=BLOCK),
        FakeJudge("evidence", provider="anthropic", vote="revise", score=3, findings=BLOCK),
    )
    assert v.status == "needs_revision"


def test_single_provider_panel_can_still_block_with_two_judges():
    v = run(
        FakeJudge("accuracy"),
        FakeJudge("critic", vote="revise", score=2, findings=BLOCK),
        FakeJudge("evidence", vote="revise", score=3, findings=BLOCK),
    )
    assert v.status == "blocked"


def test_major_finding_does_not_block():
    v = run(FakeJudge("accuracy", findings=[{"text": "Weak source", "severity": "major"}]))
    assert v.status == "verified" and v.reviews[0].blocking is False


# --- quorum ----------------------------------------------------------------

def test_default_quorum_is_majority():
    assert Panel([FakeJudge("accuracy") for _ in range(1)]).quorum == 1
    assert Panel([FakeJudge("accuracy") for _ in range(3)]).quorum == 2
    assert Panel([FakeJudge("accuracy") for _ in range(5)]).quorum == 3


def test_one_survivor_of_five_is_insufficient_jury():
    v = run(FakeJudge("accuracy"), Broken("critic"), Broken("evidence"), Broken("executive"), Broken("accuracy"))
    assert v.up == 1 and v.responded == 1 and v.requested == 5 and v.quorum == 3
    assert v.status == "insufficient_jury"
    assert len(v.errors) == 4


def test_all_judges_failing_returns_verdict_not_exception():
    v = run(Broken("accuracy"), Broken("critic"))
    assert v.status == "insufficient_jury" and v.responded == 0 and v.reviews == []


def test_quorum_met_after_one_failure():
    v = run(FakeJudge("accuracy"), Broken("critic"), FakeJudge("executive"))
    assert v.status == "verified" and v.responded == 2 and len(v.errors) == 1


def test_explicit_quorum():
    v = run(FakeJudge("accuracy"), Broken("critic"), FakeJudge("executive"), quorum=3)
    assert v.status == "insufficient_jury"


def test_bad_quorum_rejected():
    with pytest.raises(ValueError):
        Panel([FakeJudge("accuracy")], quorum=2)


# --- confidence and diversity ----------------------------------------------

def test_confidence_falls_with_disagreement():
    agree = run(FakeJudge("accuracy", score=8), FakeJudge("critic", score=8), FakeJudge("executive", score=8))
    disagree = run(FakeJudge("accuracy", score=10), FakeJudge("critic", score=2), FakeJudge("executive", score=8))
    assert agree.confidence > disagree.confidence


def test_bigger_panel_is_more_confident_at_equal_diversity():
    small = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate(["accuracy", "critic", "executive"])])
    big = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate(["accuracy", "critic", "executive", "evidence", "accuracy"])])
    assert small.diversity == big.diversity == 1.0 and big.confidence > small.confidence


def test_three_families_beat_five_clones():
    clones = run(*[FakeJudge(r) for r in ["accuracy", "critic", "executive", "evidence", "accuracy"]])
    families = run(*mixed("accuracy", "critic", "executive"))
    assert clones.up == 5 and families.up == 3 and families.confidence > clones.confidence


# --- telemetry -------------------------------------------------------------

def test_review_carries_ids_and_telemetry():
    v = run(FakeJudge("critic", findings=[{"text": "x"}]))
    r = v.reviews[0]
    assert len(r.review_id) == 12 and len(v.panel_id) == 12
    assert r.role == "critic" and r.provider == "fake" and r.model == "fake-1"
    assert r.rubric_version == "0.2" and len(r.prompt_hash) == 12
    assert r.latency_ms is not None and r.tokens_in == 100 and r.tokens_out == 50
    assert r.findings[0].adjudication is None and r.human_review is None


def test_panel_id_changes_with_roster():
    a = Panel([FakeJudge("accuracy"), FakeJudge("critic")]).panel_id
    b = Panel([FakeJudge("accuracy"), FakeJudge("evidence")]).panel_id
    assert a != b


def test_verdict_carries_request_metadata():
    req = ReviewRequest(task="t", output="o", task_type="summary", domain="finance")
    req.producer.model = "gpt-5.6"
    v = Panel([FakeJudge("accuracy")]).review(req)
    assert v.task_type == "summary" and v.domain == "finance" and v.producer.model == "gpt-5.6"
    assert v.schema_version == "0.2" and req.schema_version == "0.2"


def test_render_is_one_line():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=6))
    assert "\n" not in v.render() and "▲1" in v.render() and "jury 2/2" in v.render()
