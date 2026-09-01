"""
Turn a list of independent Reviews into one Verdict.

No LLM calls here. The rules are deliberately simple and written down so that
anyone can predict the verdict from the reviews:

  up / down    count of approve / revise votes
  score        mean of judge scores
  consensus    share of judges who sided with the majority vote
  diversity    distinct providers / judges
  confidence   consensus, discounted for small panels, wide score spread,
               and low diversity
  status       "blocked"        if any judge raised a blocking finding
               "verified"       if approvals outnumber revisions
               "needs_revision" otherwise (ties go to revision)

Reviewer reputation will later weight these votes. For now every judge counts once.
"""

from __future__ import annotations

from .protocol import Review, ReviewRequest, Verdict, Vote


def aggregate(request: ReviewRequest, reviews: list[Review], errors: list[str] | None = None) -> Verdict:
    if not reviews:
        raise ValueError("Cannot aggregate zero reviews.")

    n = len(reviews)
    up = sum(1 for r in reviews if r.vote == Vote.APPROVE)
    down = n - up
    scores = [r.score for r in reviews]
    score = sum(scores) / n

    consensus = max(up, down) / n
    diversity = len({r.provider for r in reviews}) / n

    panel_factor = n / (n + 1)  # 1 judge -> 0.5, 3 -> 0.75, 5 -> 0.83
    spread_factor = 1 - (max(scores) - min(scores)) / 10  # identical scores -> 1.0
    diversity_factor = 0.5 + 0.5 * diversity  # one provider -> 0.67 for n=3; all distinct -> 1.0
    confidence = round(consensus * panel_factor * spread_factor * diversity_factor, 3)

    if any(r.blocking for r in reviews):
        status = "blocked"
    elif up > down:
        status = "verified"
    else:
        status = "needs_revision"

    return Verdict(
        request_id=request.request_id,
        task_type=request.task_type,
        domain=request.domain,
        producer=request.producer,
        up=up,
        down=down,
        score=round(score, 2),
        consensus=round(consensus, 3),
        diversity=round(diversity, 3),
        confidence=confidence,
        status=status,
        reviews=reviews,
        errors=errors or [],
    )
