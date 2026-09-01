"""
Turn a list of independent Reviews into one Verdict.

No LLM calls here. The rules are deliberately simple and written down so that
anyone can predict the verdict from the reviews:

  up / down    count of approve / revise votes
  score        mean of judge scores
  consensus    share of judges who sided with the majority vote
  confidence   consensus, discounted for small panels and wide score spread
  status       "blocked"        if any judge raised a blocking issue
               "verified"       if approvals outnumber revisions
               "needs_revision" otherwise (ties go to revision)

Reviewer reputation will later weight these votes. For now every judge counts once.
"""

from __future__ import annotations

from .protocol import Review, Verdict, Vote


def aggregate(request_id: str, reviews: list[Review], errors: list[str] | None = None) -> Verdict:
    if not reviews:
        raise ValueError("Cannot aggregate zero reviews.")

    n = len(reviews)
    up = sum(1 for r in reviews if r.vote == Vote.APPROVE)
    down = n - up
    scores = [r.score for r in reviews]
    score = sum(scores) / n

    consensus = max(up, down) / n

    # Small panels and disagreeing scores both reduce how much we trust the result.
    panel_factor = n / (n + 1)  # 1 judge -> 0.5, 3 -> 0.75, 5 -> 0.83
    spread_factor = 1 - (max(scores) - min(scores)) / 10  # identical scores -> 1.0
    confidence = round(consensus * panel_factor * spread_factor, 3)

    if any(r.blocking for r in reviews):
        status = "blocked"
    elif up > down:
        status = "verified"
    else:
        status = "needs_revision"

    return Verdict(
        request_id=request_id,
        up=up,
        down=down,
        score=round(score, 2),
        consensus=round(consensus, 3),
        confidence=confidence,
        status=status,
        reviews=reviews,
        errors=errors or [],
    )
