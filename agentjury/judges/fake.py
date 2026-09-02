"""A judge that returns a canned opinion. For tests and offline demos.

`fail_times` makes the first N calls raise ConnectionError (tests retry).
`garbage_times` makes the following N calls return non-JSON (tests repair).
"""

from __future__ import annotations

import json
import time

from .base import Completion, Judge


class FakeJudge(Judge):
    provider = "fake"

    def __init__(self, role: str, vote: str = "approve", score: float = 8.0,
                 reason: str = "Looks fine.", findings: list[dict] | None = None,
                 provider: str | None = None, fail_times: int = 0, garbage_times: int = 0,
                 delay: float = 0.0, params: dict | None = None):
        super().__init__(role, model="fake-1", timeout=5.0)
        self.delay = delay
        if params:
            self.params = params
        if provider:  # lets tests simulate multi-provider panels
            self.provider = provider
        self._canned = {"vote": vote, "score": score, "reason": reason,
                        "findings": findings or [], "confidence": 0.8}
        self.fail_times = fail_times
        self.garbage_times = garbage_times
        self.calls = 0

    def complete(self, system: str, user: str) -> Completion:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.calls <= self.fail_times:
            raise ConnectionError("simulated outage")
        if self.calls <= self.fail_times + self.garbage_times:
            return Completion(text="Sure! Here is my review: it looks fine to me.", tokens_in=100, tokens_out=20)
        return Completion(text=json.dumps(self._canned), tokens_in=100, tokens_out=50)
