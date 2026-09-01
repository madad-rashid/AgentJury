"""
A Panel is a set of judges that review the same request independently.

Judges run concurrently. Each one sees only the ReviewRequest. A judge that
crashes (network error, malformed JSON) is recorded in `Verdict.errors`. If
fewer than `quorum` judges respond, the verdict status is `insufficient_jury`
and the votes are informational only.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from .aggregate import aggregate, default_quorum
from .judges.base import Judge
from .protocol import Review, ReviewRequest, Verdict


class Panel:
    def __init__(self, judges: list[Judge], quorum: int | None = None, max_workers: int | None = None):
        if not judges:
            raise ValueError("A panel needs at least one judge.")
        if quorum is not None and not 1 <= quorum <= len(judges):
            raise ValueError(f"quorum must be between 1 and {len(judges)}, got {quorum}")
        self.judges = judges
        self.quorum = quorum if quorum is not None else default_quorum(len(judges))
        self.max_workers = max_workers or len(judges)

    @property
    def panel_id(self) -> str:
        roster = "|".join(sorted(f"{j.name}:{j.model}:{j.prompt_hash}" for j in self.judges))
        return hashlib.sha256(roster.encode()).hexdigest()[:12]

    def review(self, request: ReviewRequest) -> Verdict:
        reviews: list[Review] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(j.review, request): j for j in self.judges}
            for future in as_completed(futures):
                judge = futures[future]
                try:
                    reviews.append(future.result())
                except Exception as exc:  # noqa: BLE001 - one bad judge must not sink the panel
                    errors.append(f"{judge.name}: {type(exc).__name__}: {exc}")

        # Keep judge order stable in the output regardless of who finished first.
        order = {j.name: i for i, j in enumerate(self.judges)}
        reviews.sort(key=lambda r: order.get(r.judge, 999))

        return aggregate(
            request, reviews, errors,
            requested=len(self.judges), quorum=self.quorum, panel_id=self.panel_id,
        )
