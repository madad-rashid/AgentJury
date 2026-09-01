"""A judge that returns a canned opinion. For tests and offline demos."""

from __future__ import annotations

import json

from .base import Completion, Judge


class FakeJudge(Judge):
    provider = "fake"

    def __init__(self, role: str, vote: str = "approve", score: float = 8.0,
                 reason: str = "Looks fine.", findings: list[dict] | None = None,
                 provider: str | None = None):
        super().__init__(role, model="fake-1")
        if provider:  # lets tests simulate multi-provider panels
            self.provider = provider
        self._canned = {"vote": vote, "score": score, "reason": reason,
                        "findings": findings or [], "confidence": 0.8}

    def complete(self, system: str, user: str) -> Completion:
        return Completion(text=json.dumps(self._canned), tokens_in=100, tokens_out=50)
