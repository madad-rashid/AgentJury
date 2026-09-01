"""
A Panel is a set of judges that review the same request independently.

Judges run concurrently. Each one sees only the ReviewRequest. A judge that
crashes (network error, malformed JSON) is recorded in `Verdict.errors` and
the remaining judges still produce a verdict.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from .aggregate import aggregate
from .judges.base import Judge
from .protocol import Review, ReviewRequest, Verdict


class Panel:
    def __init__(self, judges: list[Judge], max_workers: int | None = None):
        if not judges:
            raise ValueError("A panel needs at least one judge.")
        self.judges = judges
        self.max_workers = max_workers or len(judges)

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

        if not reviews:
            raise RuntimeError("Every judge failed:\n" + "\n".join(errors))

        # Keep judge order stable in the output regardless of who finished first.
        order = {j.name: i for i, j in enumerate(self.judges)}
        reviews.sort(key=lambda r: order.get(r.judge, 999))

        return aggregate(request, reviews, errors)
