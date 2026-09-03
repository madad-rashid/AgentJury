"""AgentJury: peer review for AI agents."""

from .aggregate import aggregate
from .panel import Panel
from .protocol import (
    SCHEMA_VERSION,
    Artifact,
    Finding,
    HumanReview,
    Producer,
    Review,
    ReviewRequest,
    Verdict,
    Vote,
)

__version__ = "0.4.3"

__all__ = [
    "SCHEMA_VERSION", "Artifact", "Finding", "HumanReview", "Producer",
    "Review", "ReviewRequest", "Verdict", "Vote", "Panel", "aggregate",
]
