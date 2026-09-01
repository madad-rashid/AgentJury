"""
The AgentJury protocol.

Three objects flow through the system:

    ReviewRequest  ->  [Judge, Judge, Judge]  ->  [Review, Review, Review]  ->  Verdict

A ReviewRequest describes a task an agent completed. Each Judge sees only the
request (never the other judges' opinions) and returns a Review. The
Aggregator turns the Reviews into a single Verdict.

Any agent framework that can produce a ReviewRequest can use AgentJury.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Input side
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    """A file or blob the agent produced alongside its main output."""

    name: str
    content: str
    media_type: str = "text/plain"


class Agent(BaseModel):
    """Who did the work. All fields optional so any framework can fill it in."""

    name: str | None = None
    framework: str | None = None  # e.g. "hermes", "claude-code", "crewai"
    model: str | None = None  # e.g. "gpt-5.6-sol", "claude-fable-5-1"


class ReviewRequest(BaseModel):
    """Everything a judge needs to evaluate one completed task."""

    request_id: str = Field(default_factory=_new_id)
    task: str = Field(description="The instruction the agent was given.")
    output: str = Field(description="What the agent produced.")
    context: str | None = Field(
        default=None,
        description="Background the judges should know: domain, prior decisions, house style.",
    )
    artifacts: list[Artifact] = Field(default_factory=list)
    agent: Agent = Field(default_factory=Agent)
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Output side
# ---------------------------------------------------------------------------


class Vote(str, Enum):
    APPROVE = "approve"  # rendered as ▲
    REVISE = "revise"  # rendered as ▼


class Review(BaseModel):
    """One judge's independent assessment of a ReviewRequest."""

    judge: str = Field(description="Judge identifier, e.g. 'accuracy/anthropic'.")
    model: str = Field(description="Underlying model that produced this review.")
    vote: Vote
    score: float = Field(ge=0, le=10)
    reason: str = Field(description="One or two sentences justifying the vote.")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems found. Empty list means none.",
    )
    blocking: bool = Field(
        default=False,
        description="True if any issue is serious enough to veto verification.",
    )
    created_at: datetime = Field(default_factory=_now)


class Verdict(BaseModel):
    """The aggregate of all Reviews for one ReviewRequest."""

    request_id: str
    up: int = Field(description="Number of APPROVE votes.")
    down: int = Field(description="Number of REVISE votes.")
    score: float = Field(ge=0, le=10, description="Mean of judge scores.")
    consensus: float = Field(
        ge=0, le=1, description="Share of judges who agree with the majority vote."
    )
    confidence: float = Field(
        ge=0, le=1, description="How much to trust this verdict. Rises with agreement and judge count."
    )
    status: Literal["verified", "needs_revision", "blocked"]
    reviews: list[Review]
    errors: list[str] = Field(
        default_factory=list,
        description="Judges that failed to return a review, with the reason.",
    )
    created_at: datetime = Field(default_factory=_now)

    def render(self) -> str:
        """Compact one-line summary, Reddit style."""
        return f"▲{self.up} ▼{self.down}  score {self.score:.1f}  consensus {self.consensus:.0%}  {self.status}"
