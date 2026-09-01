"""A judge that returns a canned opinion. For tests and offline demos."""

from __future__ import annotations

import json

from .base import Judge


class FakeJudge(Judge):
    provider = "fake"

    def __init__(self, role: str, vote: str = "approve", score: float = 8.0,
                 reason: str = "Looks fine.", issues: list[str] | None = None,
                 blocking: bool = False):
        super().__init__(role, model="fake-1")
        self._canned = {
            "vote": vote, "score": score, "reason": reason,
            "issues": issues or [], "blocking": blocking,
        }

    def complete(self, system: str, user: str) -> str:
        return json.dumps(self._canned)
