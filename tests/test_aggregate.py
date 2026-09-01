"""Tests for the aggregator and panel. No API keys needed: uses FakeJudge."""

import pytest

from agentjury import Panel, ReviewRequest, aggregate
from agentjury.aggregate import default_quorum
from agentjury.judges import FakeJudge

REQ = ReviewRequest(task="Write a haiku about rain.", output="Rain taps the window...")
BLOCK = [{"text": "Fabricated source", "severity": "blocking"}]
PROVIDERS = ["openai", "anthropic", "google"]


from agentjury.judges import register_roles
register_roles({r: f"Test role {r}." for r in ["a", "b", "c", "d", "e", "domain"]})


def run(*judges, quorum=None):
    return Panel(list(judges), quorum=quorum).review(REQ)


def mixed(*roles, **kw):
    """Judges from rotating distinct providers."""
    return [FakeJudge(r, provider=PROVIDERS[i % 3], **kw) for i, r in enumerate(roles)]


def broken(role, provider=None):
    return FakeJudge(role, provider=provider, fail_times=99)


# --- votes -----------------------------------------------------------------

def test_unanimous_approval_is_verified():
    v = run(*mixed("accuracy", "critic", "executive", score=9))
    assert v.up == 3 and v.down == 0 and v.status == "verified" and v.consensus == 1.0


def test_majority_approve_is_verified():
    v = run(FakeJudge("accuracy", provider="openai"), FakeJudge("critic", provider="anthropic", vote="revise", score=5),
            FakeJudge("executive", provider="openai"))
    assert v.up == 2 and v.down == 1 and v.status == "verified"


def test_tie_needs_revision():
    v = run(FakeJudge("accuracy", provider="openai"), FakeJudge("critic", provider="anthropic", vote="revise", score=4))
    assert v.status == "needs_revision"


# --- abstain ---------------------------------------------------------------

def test_abstention_is_not_an_approval():
    v = run(FakeJudge("accuracy", provider="openai"), FakeJudge("domain", provider="anthropic", vote="abstain", score=5),
            FakeJudge("critic", provider="google", vote="revise", score=4))
    assert v.up == 1 and v.down == 1 and v.abstained == 1
    assert v.status == "needs_revision"  # 1-1 tie among voters, not 2-1 approve


def test_all_abstain_is_insufficient_jury():
    v = run(*mixed("a", "b", "c", vote="abstain"))
    assert v.status == "insufficient_jury" and v.abstained == 3 and v.up == v.down == 0


def test_abstentions_count_against_quorum():
    # 3 requested, quorum 2, only 1 actually voted
    v = run(FakeJudge("accuracy", provider="openai"), FakeJudge("b", provider="anthropic", vote="abstain"),
            FakeJudge("c", provider="google", vote="abstain"))
    assert v.status == "insufficient_jury"


# --- blocking: no single judge can veto ------------------------------------

def test_one_blocking_judge_cannot_block_alone():
    v = run(*mixed("accuracy", "executive"), FakeJudge("critic", provider="google", vote="revise", score=3, findings=BLOCK))
    assert v.up == 2 and v.status == "needs_revision"


def test_blocking_from_two_providers_blocks():
    v = run(FakeJudge("accuracy", provider="openai"),
            FakeJudge("critic", provider="anthropic", vote="revise", score=2, findings=BLOCK),
            FakeJudge("evidence", provider="google", vote="revise", score=3, findings=BLOCK))
    assert v.status == "blocked"


def test_two_blocks_from_same_provider_do_not_block_in_mixed_panel():
    v = run(FakeJudge("accuracy", provider="openai"),
            FakeJudge("critic", provider="anthropic", vote="revise", score=2, findings=BLOCK),
            FakeJudge("evidence", provider="anthropic", vote="revise", score=3, findings=BLOCK))
    assert v.status == "needs_revision"


def test_single_provider_panel_can_still_block_with_two_judges():
    v = run(FakeJudge("accuracy"), FakeJudge("critic", vote="revise", score=2, findings=BLOCK),
            FakeJudge("evidence", vote="revise", score=3, findings=BLOCK))
    assert v.status == "blocked"


def test_blocking_is_derived_from_findings_not_trusted():
    from agentjury import Review
    r = Review(judge="x/fake", role="x", provider="fake", model="m", vote="approve", score=9, reason="r",
               findings=[{"text": "bad", "severity": "blocking"}], blocking=False,
               rubric_version="0.3", prompt_hash="abc")
    assert r.blocking is True
    r2 = Review(judge="x/fake", role="x", provider="fake", model="m", vote="approve", score=9, reason="r",
                findings=[], blocking=True, rubric_version="0.3", prompt_hash="abc")
    assert r2.blocking is False


# --- quorum ----------------------------------------------------------------

@pytest.mark.parametrize("n,q", [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3), (6, 4)])
def test_default_quorum_is_strict_majority(n, q):
    assert default_quorum(n) == q
    assert Panel([FakeJudge("accuracy") for _ in range(n)]).quorum == q


def test_two_of_four_is_not_a_quorum():
    v = run(FakeJudge("a", provider="openai"), FakeJudge("b", provider="anthropic"),
            broken("c", "openai"), broken("d", "anthropic"))
    assert v.up == 2 and v.status == "insufficient_jury"


def test_one_of_two_is_not_a_quorum():
    v = run(FakeJudge("a", provider="openai"), broken("b", "anthropic"))
    assert v.status == "insufficient_jury"


def test_one_survivor_of_five_is_insufficient_jury():
    v = run(FakeJudge("accuracy"), broken("critic"), broken("evidence"), broken("executive"), broken("accuracy"))
    assert v.up == 1 and v.responded == 1 and v.requested == 5 and v.quorum == 3
    assert v.status == "insufficient_jury" and len(v.errors) == 4


def test_all_judges_failing_returns_verdict_not_exception():
    v = run(broken("accuracy"), broken("critic"))
    assert v.status == "insufficient_jury" and v.responded == 0 and v.reviews == []


def test_quorum_met_after_one_failure():
    v = run(FakeJudge("accuracy", provider="openai"), broken("critic", "anthropic"), FakeJudge("executive", provider="google"))
    assert v.status == "verified" and v.responded == 2 and len(v.errors) == 1


def test_explicit_quorum():
    v = run(FakeJudge("accuracy", provider="openai"), broken("critic", "anthropic"),
            FakeJudge("executive", provider="google"), quorum=3)
    assert v.status == "insufficient_jury"


def test_bad_quorum_rejected():
    with pytest.raises(ValueError):
        Panel([FakeJudge("accuracy")], quorum=2)


# --- provider floor --------------------------------------------------------

def test_multi_provider_panel_needs_two_providers_to_verify():
    """The dissenting family's judge failed; the surviving two share a provider."""
    v = run(FakeJudge("accuracy", provider="openai"), broken("critic", "anthropic"), FakeJudge("executive", provider="openai"))
    assert v.up == 2 and v.responded == 2  # quorum of 2 is met...
    assert v.status == "insufficient_jury"  # ...but independence was lost


def test_single_provider_panel_is_not_penalised_for_being_single():
    v = run(FakeJudge("accuracy"), FakeJudge("critic"), FakeJudge("executive"))
    assert v.status == "verified"


# --- retry and repair ------------------------------------------------------

def test_transient_failure_is_retried():
    j = FakeJudge("accuracy", fail_times=1)
    v = run(j)
    assert v.status == "verified" and j.calls == 2 and v.errors == []


def test_persistent_failure_gives_up_after_one_retry():
    j = FakeJudge("accuracy", fail_times=5)
    v = run(j)
    assert v.status == "insufficient_jury" and j.calls == 2 and len(v.errors) == 1


def test_malformed_json_gets_one_repair_attempt():
    j = FakeJudge("accuracy", garbage_times=1)
    v = run(j)
    assert v.status == "verified" and j.calls == 2
    assert v.reviews[0].tokens_out == 70  # both calls counted


def test_persistent_garbage_fails_the_judge():
    j = FakeJudge("accuracy", garbage_times=5)
    v = run(j)
    assert v.status == "insufficient_jury" and j.calls == 2 and "malformed" in v.errors[0].lower() or "JSON" in v.errors[0]


# --- confidence and diversity ----------------------------------------------

def test_confidence_falls_with_disagreement():
    agree = run(*mixed("a", "b", "c", score=8))
    disagree = run(FakeJudge("a", provider="openai", score=10), FakeJudge("b", provider="anthropic", score=2),
                   FakeJudge("c", provider="google", score=8))
    assert agree.confidence > disagree.confidence


def test_bigger_panel_is_more_confident_at_equal_diversity():
    small = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate("abc")])
    big = run(*[FakeJudge(r, provider=f"p{i}") for i, r in enumerate("abcde")])
    assert small.diversity == big.diversity == 1.0 and big.confidence > small.confidence


def test_three_families_beat_five_clones():
    clones = run(*[FakeJudge(r) for r in "abcde"])
    families = run(*mixed("a", "b", "c"))
    assert clones.up == 5 and families.up == 3 and families.confidence > clones.confidence


# --- telemetry -------------------------------------------------------------

def test_review_carries_ids_params_and_telemetry():
    v = run(FakeJudge("critic", findings=[{"text": "x"}]))
    r = v.reviews[0]
    assert len(r.review_id) == 12 and r.request_id == REQ.request_id and r.panel_id == v.panel_id
    assert r.role == "critic" and r.provider == "fake" and r.model == "fake-1"
    assert r.rubric_version == "0.3" and len(r.prompt_hash) == 12
    assert r.params["timeout"] == 5.0
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
    assert v.schema_version == "0.3" and req.schema_version == "0.3"


def test_render_is_one_line():
    v = run(FakeJudge("accuracy", provider="openai"), FakeJudge("critic", provider="anthropic", vote="revise", score=6),
            FakeJudge("d", provider="google", vote="abstain"))
    line = v.render()
    assert "\n" not in line and "▲1" in line and "jury 2/3 (1 abstained)" in line
