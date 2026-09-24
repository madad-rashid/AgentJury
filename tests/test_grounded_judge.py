"""Model reviews fail closed when their findings lack literal evidence."""

import json

import pytest

from agentjury.judges.base import Completion, Judge
from agentjury.panel import Panel
from agentjury.protocol import ReviewRequest, Vote


REQUEST = ReviewRequest(
    task="Calculate 17 multiplied by 19.",
    output="The product is 324.",
    context="The correct product is 323.",
)


class ScriptedJudge(Judge):
    provider = "scripted"

    def __init__(self, replies: list[str], role: str = "accuracy"):
        super().__init__(role, "test", retries=0)
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system: str, user: str) -> Completion:
        self.calls += 1
        return Completion(self.replies.pop(0))


def opinion(*, evidence: dict | None = None, vote: str = "revise", findings: bool = True) -> str:
    item = {"text": "The product is wrong.", "severity": "blocking"}
    if evidence is not None:
        item["evidence"] = evidence
    return json.dumps({
        "vote": vote,
        "score": 3 if vote == "revise" else 9,
        "reason": "Model-invented extra claim must not be displayed.",
        "findings": [item] if findings else [],
    })


VALID_EVIDENCE = {
    "output_quote": "The product is 324.",
    "basis_source": "context",
    "basis_quote": "The correct product is 323.",
}


def test_valid_evidence_is_saved_with_neutral_reason():
    judge = ScriptedJudge([opinion(evidence=VALID_EVIDENCE)])
    review = judge.review(REQUEST)
    assert review.vote == Vote.REVISE
    assert review.findings[0].evidence.basis_quote == "The correct product is 323."
    assert "Model-invented" not in review.reason
    assert "1 finding" in review.reason
    assert judge.calls == 1


def test_invalid_first_response_uses_one_repair():
    judge = ScriptedJudge([opinion(), opinion(evidence=VALID_EVIDENCE)])
    review = judge.review(REQUEST)
    assert review.vote == Vote.REVISE
    assert judge.calls == 2


def test_invalid_evidence_fails_after_one_repair_without_echoing_claim():
    judge = ScriptedJudge([opinion(), opinion()])
    with pytest.raises(ValueError, match="evidence") as failure:
        judge.review(REQUEST)
    assert "Model-invented" not in str(failure.value)
    assert judge.calls == 2


def test_revise_without_findings_cannot_bypass_evidence_gate():
    judge = ScriptedJudge([opinion(findings=False), opinion(findings=False)])
    with pytest.raises(ValueError, match="evidence"):
        judge.review(REQUEST)
    assert judge.calls == 2


def test_approve_reason_does_not_repeat_model_claim():
    judge = ScriptedJudge([opinion(vote="approve", findings=False)])
    review = judge.review(REQUEST)
    assert review.vote == Vote.APPROVE
    assert "Model-invented" not in review.reason
    assert judge.calls == 1


def test_failed_judge_does_not_count_toward_panel_quorum():
    bad = ScriptedJudge([opinion(), opinion()])
    good = ScriptedJudge([opinion(vote="approve", findings=False)], role="critic")
    verdict = Panel([bad, good]).review(REQUEST)
    assert verdict.status == "insufficient_jury"
    assert verdict.responded == 1
    assert verdict.up == 1
    assert len(verdict.errors) == 1
    assert "Model-invented" not in verdict.errors[0]
