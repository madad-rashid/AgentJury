"""Display checked excerpts without upgrading them to verified facts."""

import json

from agentjury.aggregate import aggregate
from agentjury.cli import print_verdict
from agentjury.protocol import Finding, FindingEvidence, Review, ReviewRequest, Verdict, Vote


def sample_verdict() -> Verdict:
    request = ReviewRequest(task="Check the price.", output="Price is $12.", context="Price is $1.20.")
    finding = Finding(
        text="Price differs from supplied context.", severity="major",
        evidence=FindingEvidence(
            output_quote="Price is $12.", basis_source="context", basis_quote="Price is $1.20."
        ),
    )
    review = Review(
        judge="accuracy/test", role="accuracy", provider="test", model="test",
        vote=Vote.REVISE, score=3, reason="Reviewer requests revision: 1 finding with checked excerpts.",
        findings=[finding], rubric_version="0.4", prompt_hash="test",
    )
    return aggregate(request, [review], requested=1, requested_providers=1)


def test_display_marks_checked_excerpts(capsys):
    print_verdict(sample_verdict())
    shown = capsys.readouterr().out
    assert "Price differs from supplied context. [excerpts checked]" in shown
    assert "verified fact" not in shown


def test_old_verdict_without_evidence_still_loads_and_displays(capsys):
    old = sample_verdict().model_dump(mode="json")
    del old["reviews"][0]["findings"][0]["evidence"]
    verdict = Verdict.model_validate_json(json.dumps(old))
    assert verdict.reviews[0].findings[0].evidence is None
    print_verdict(verdict)
    assert "[excerpts checked]" not in capsys.readouterr().out
