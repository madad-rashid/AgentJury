"""
Turn a list of independent Reviews into one Verdict.

No LLM calls here. The rules are written down so anyone can predict the verdict:

  up / down    count of approve / revise votes
  score        mean of judge scores
  consensus    share of judges who sided with the majority vote
  diversity    distinct providers / responding judges
  confidence   heuristic index: consensus, discounted for small panels, wide
               score spread, and low diversity. NOT a calibrated probability.

  status
    insufficient_jury  fewer than `quorum` judges responded. Votes are reported
                       but no verdict is reached. Callers must not treat this as a pass.
    blocked            blocking findings from at least two providers (or from at
                       least two judges when the panel has only one provider).
                       No single judge can block on its own.
    needs_revision     majority revise, a tie, or exactly one blocking source.
    verified           majority approve and no blocking finding.

Reviewer reputation will later weight these votes. For now every judge counts once.
"""

from __future__ import annotations

from .protocol import Review, ReviewRequest, Verdict, Vote


def default_quorum(requested: int) -> int:
    """Simple majority of the requested panel: 1->1, 2->1, 3->2, 4->2, 5->3."""
    return max(1, (requested + 1) // 2)


def aggregate(
    request: ReviewRequest,
    reviews: list[Review],
    errors: list[str] | None = None,
    *,
    requested: int | None = None,
    quorum: int | None = None,
    panel_id: str | None = None,
) -> Verdict:
    requested = requested if requested is not None else len(reviews)
    quorum = quorum if quorum is not None else default_quorum(requested)
    n = len(reviews)

    if n == 0:
        return Verdict(
            request_id=request.request_id, panel_id=panel_id,
            requested=requested, responded=0, quorum=quorum,
            task_type=request.task_type, domain=request.domain, producer=request.producer,
            up=0, down=0, score=0.0, consensus=0.0, diversity=0.0, confidence=0.0,
            status="insufficient_jury", reviews=[], errors=errors or [],
        )

    up = sum(1 for r in reviews if r.vote == Vote.APPROVE)
    down = n - up
    scores = [r.score for r in reviews]
    score = sum(scores) / n

    consensus = max(up, down) / n
    providers = {r.provider for r in reviews}
    diversity = len(providers) / n

    panel_factor = n / (n + 1)  # 1 judge -> 0.5, 3 -> 0.75, 5 -> 0.83
    spread_factor = 1 - (max(scores) - min(scores)) / 10  # identical scores -> 1.0
    diversity_factor = 0.5 + 0.5 * diversity  # all one provider (n=3) -> 0.67; all distinct -> 1.0
    confidence = round(consensus * panel_factor * spread_factor * diversity_factor, 3)

    blocking_reviews = [r for r in reviews if r.blocking]
    blocking_providers = {r.provider for r in blocking_reviews}
    independent_blocks = len(blocking_providers) >= 2 or (len(providers) == 1 and len(blocking_reviews) >= 2)

    if n < quorum:
        status = "insufficient_jury"
    elif independent_blocks:
        status = "blocked"
    elif blocking_reviews or up <= down:
        status = "needs_revision"
    else:
        status = "verified"

    return Verdict(
        request_id=request.request_id,
        panel_id=panel_id,
        requested=requested,
        responded=n,
        quorum=quorum,
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
