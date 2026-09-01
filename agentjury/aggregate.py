"""
Turn a list of independent Reviews into one Verdict.

No LLM calls here. The rules are written down so anyone can predict the verdict:

  voters       responding judges who did not abstain
  up / down    count of approve / revise votes among voters
  score        mean of voters' scores
  consensus    share of voters who sided with the majority vote
  diversity    distinct providers among voters / voters
  confidence   heuristic index: consensus, discounted for small panels, wide
               score spread, and low diversity. NOT a calibrated probability.

  status
    insufficient_jury  fewer than `quorum` judges voted, OR the panel was built
                       from two or more providers but only one provider's judges
                       voted. Votes are reported; no verdict is reached.
    blocked            blocking findings from at least two providers (or from at
                       least two judges when the panel has only one provider).
                       No single judge can block on its own.
    needs_revision     majority revise, a tie, or exactly one blocking source.
    verified           majority approve and no blocking finding.

  quorum       default is a strict majority of requested judges:
               1->1, 2->2, 3->2, 4->3, 5->3, 6->4

Reviewer reputation will later weight these votes. For now every voter counts once.
"""

from __future__ import annotations

from .protocol import Review, ReviewRequest, Verdict, Vote


def default_quorum(requested: int) -> int:
    """Strict majority of the requested panel."""
    return max(1, requested // 2 + 1)


def _empty(request: ReviewRequest, reviews, errors, requested, quorum, panel_id) -> Verdict:
    return Verdict(
        request_id=request.request_id, panel_id=panel_id,
        requested=requested, responded=len(reviews), abstained=len(reviews), quorum=quorum,
        task_type=request.task_type, domain=request.domain, producer=request.producer,
        up=0, down=0, score=0.0, consensus=0.0, diversity=0.0, confidence=0.0,
        status="insufficient_jury", reviews=reviews, errors=errors or [],
    )


def aggregate(
    request: ReviewRequest,
    reviews: list[Review],
    errors: list[str] | None = None,
    *,
    requested: int | None = None,
    quorum: int | None = None,
    panel_id: str | None = None,
    requested_providers: int | None = None,
) -> Verdict:
    requested = requested if requested is not None else len(reviews)
    quorum = quorum if quorum is not None else default_quorum(requested)

    voters = [r for r in reviews if r.vote != Vote.ABSTAIN]
    abstained = len(reviews) - len(voters)
    if not voters:
        return _empty(request, reviews, errors, requested, quorum, panel_id)

    n = len(voters)
    up = sum(1 for r in voters if r.vote == Vote.APPROVE)
    down = n - up
    scores = [r.score for r in voters]
    score = sum(scores) / n

    consensus = max(up, down) / n
    providers = {r.provider for r in voters}
    diversity = len(providers) / n

    panel_factor = n / (n + 1)  # 1 voter -> 0.5, 3 -> 0.75, 5 -> 0.83
    spread_factor = 1 - (max(scores) - min(scores)) / 10  # identical scores -> 1.0
    diversity_factor = 0.5 + 0.5 * diversity  # all one provider (n=3) -> 0.67; all distinct -> 1.0
    confidence = round(consensus * panel_factor * spread_factor * diversity_factor, 3)

    blocking_reviews = [r for r in voters if r.blocking]
    blocking_providers = {r.provider for r in blocking_reviews}
    independent_blocks = len(blocking_providers) >= 2 or (len(providers) == 1 and len(blocking_reviews) >= 2)

    # A multi-provider panel that only heard from one provider has lost the
    # independence it was built for, so it cannot reach a verdict.
    wanted_providers = requested_providers if requested_providers is not None else len(providers)
    provider_floor = min(2, wanted_providers)

    if n < quorum or len(providers) < provider_floor:
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
        responded=len(reviews),
        abstained=abstained,
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
