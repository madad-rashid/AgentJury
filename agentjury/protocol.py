"""
The AgentJury protocol. Schema version is SCHEMA_VERSION below.

    ReviewRequest  ->  [Judge, Judge, Judge]  ->  [Review, Review, Review]  ->  Verdict

Every field that reputation will later need is captured from the first review:
who produced the output, who judged it, with which prompt, at what cost, and
a slot for a human to adjudicate each finding. Reputation weighting is not
active yet; the data for it is.

Any agent framework that can produce a ReviewRequest can use AgentJury.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from typing import Any

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.4"


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


class Producer(BaseModel):
    """Who did the work. Recording the model lets us later measure whether
    judges favour outputs from their own model family."""

    agent: str | None = Field(default=None, description="Agent name, e.g. 'hermes-finance'.")
    framework: str | None = Field(default=None, description="e.g. 'hermes', 'claude-code', 'crewai'.")
    provider: str | None = Field(default=None, description="e.g. 'openai', 'anthropic'.")
    model: str | None = Field(default=None, description="e.g. 'gpt-5.6', 'claude-fable-5-1'.")


class ReviewRequest(BaseModel):
    """Everything a judge needs to evaluate one completed task."""

    schema_version: str = SCHEMA_VERSION
    request_id: str = Field(default_factory=_new_id)
    task: str = Field(description="The instruction the agent was given.")
    output: str = Field(description="What the agent produced.")
    context: str | None = Field(
        default=None,
        description="Background the judges should know: domain, prior decisions, house style.",
    )
    task_type: str | None = Field(
        default=None,
        description="Kind of work, e.g. 'financial_analysis', 'code_review', 'summary'. Reputation is tracked per task_type.",
    )
    domain: str | None = Field(
        default=None, description="Subject area, e.g. 'private_credit', 'python', 'marketing'."
    )
    artifacts: list[Artifact] = Field(default_factory=list)
    producer: Producer = Field(default_factory=Producer)
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Output side
# ---------------------------------------------------------------------------


class Vote(str, Enum):
    APPROVE = "approve"  # rendered as ▲
    REVISE = "revise"  # rendered as ▼
    ABSTAIN = "abstain"  # judge could not evaluate (e.g. no context to check against); not counted


Severity = Literal["minor", "major", "blocking"]
Adjudication = Literal["correct", "partially_correct", "wrong"]


class Finding(BaseModel):
    """One specific problem a judge raised. Adjudicated individually by a human,
    so a review with five findings and one mistake keeps credit for four."""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    text: str
    severity: Severity = "minor"
    adjudication: Adjudication | None = Field(
        default=None, description="Set by a human later. None means not yet reviewed."
    )
    adjudicated_at: datetime | None = None


class HumanReview(BaseModel):
    """A human's overall judgement of one judge's review."""

    verdict: Literal["agree", "partial", "disagree"]
    note: str | None = None
    reviewed_at: datetime = Field(default_factory=_now)


class Review(BaseModel):
    """One judge's independent assessment of a ReviewRequest."""

    review_id: str = Field(default_factory=_new_id)
    request_id: str | None = Field(default=None, description="The ReviewRequest this review is of.")
    panel_id: str | None = Field(default=None, description="The panel this review was part of.")
    judge: str = Field(description="Display name, e.g. 'critic/anthropic'.")
    role: str = Field(description="Judge role, e.g. 'critic'.")
    provider: str = Field(description="e.g. 'openai', 'anthropic', 'fake'.")
    model: str = Field(description="Underlying model that produced this review.")

    vote: Vote
    score: float = Field(ge=0, le=10)
    reason: str = Field(description="One or two sentences justifying the vote.")
    findings: list[Finding] = Field(default_factory=list)
    blocking: bool = Field(
        default=False,
        description="Derived: True iff any finding has severity 'blocking'. Any supplied value is overwritten.",
    )
    self_confidence: float | None = Field(
        default=None, ge=0, le=1,
        description="Judge's own stated confidence. Weak signal; recorded, not trusted.",
    )

    rubric_version: str = Field(description="Version of the role definitions used.")
    prompt_hash: str = Field(description="Hash of the exact system prompt sent to the judge.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Model parameters that affect behaviour: effort, thinking, max_tokens, temperature...",
    )
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    response_id: str | None = Field(default=None, description="Provider's response ID, for audit.")

    human_review: HumanReview | None = None
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _derive_blocking(self) -> "Review":
        self.blocking = any(f.severity == "blocking" for f in self.findings)
        return self


class Verdict(BaseModel):
    """The aggregate of all Reviews for one ReviewRequest."""

    schema_version: str = SCHEMA_VERSION
    request_id: str
    panel_id: str | None = Field(default=None, description="Hash of the judge roster that produced this verdict.")
    requested: int = Field(description="Judges asked to review.")
    responded: int = Field(description="Judges that returned a valid review.")
    abstained: int = Field(default=0, description="Responding judges that voted abstain; excluded from votes.")
    quorum: int = Field(description="Minimum non-abstaining responses required for a verdict.")
    task_type: str | None = None
    domain: str | None = None
    producer: Producer = Field(default_factory=Producer)

    up: int = Field(description="Number of APPROVE votes.")
    down: int = Field(description="Number of REVISE votes.")
    score: float = Field(ge=0, le=10, description="Mean of judge scores.")
    consensus: float = Field(ge=0, le=1, description="Share of judges who agree with the majority vote.")
    diversity: float = Field(
        ge=0, le=1,
        description="Distinct providers / judges. Three families voting 3-0 beats one family voting 3-0.",
    )
    confidence: float = Field(
        ge=0, le=1,
        description=(
            "HEURISTIC INDEX, not a calibrated probability. Rises with agreement, panel size, "
            "and provider diversity. Will be calibrated against human adjudication once enough exists."
        ),
    )
    status: Literal["verified", "needs_revision", "blocked", "insufficient_jury"] = Field(
        description=(
            "verified: majority approve, no blocking finding. "
            "needs_revision: majority revise, a tie, or one blocking finding. "
            "blocked: blocking findings from two or more providers. "
            "insufficient_jury: fewer than quorum judges voted, or a multi-provider panel heard from "
            "only one provider; votes are informational only."
        )
    )
    reviews: list[Review]
    errors: list[str] = Field(
        default_factory=list, description="Judges that failed to return a review, with the reason."
    )
    human_verdict: Literal["correct", "flawed"] | None = Field(
        default=None, description="A human's judgement of the producer's output itself, independent of the judges."
    )
    human_note: str | None = None
    adjudicated_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)

    def render(self) -> str:
        """Compact one-line summary, Reddit style."""
        jury = f"{self.responded - self.abstained}/{self.requested}"
        if self.abstained:
            jury += f" ({self.abstained} abstained)"
        return (
            f"▲{self.up} ▼{self.down}  score {self.score:.1f}  "
            f"consensus {self.consensus:.0%}  diversity {self.diversity:.0%}  jury {jury}  {self.status}"
        )
