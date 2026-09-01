"""AgentJury: an open peer-review and reputation layer for AI agents."""

from .aggregate import aggregate
from .panel import Panel
from .protocol import (
    Agent,
    Artifact,
    Review,
    ReviewRequest,
    Verdict,
    Vote,
)

__version__ = "0.0.1"

__all__ = [
    "Agent", "Artifact", "Review", "ReviewRequest", "Verdict", "Vote",
    "Panel", "aggregate",
]
