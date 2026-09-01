"""
Judge interface.

A Judge takes a ReviewRequest and returns a Review. It sees nothing else:
not other judges' votes, not previous verdicts. That independence is the
point. Concrete judges (OpenAI, Anthropic, ...) only have to implement
one method: `complete(system, user) -> str`.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, ValidationError

from ..protocol import Review, ReviewRequest, Vote

# ---------------------------------------------------------------------------
# Roles: what each judge is looking for
# ---------------------------------------------------------------------------

ROLES: dict[str, str] = {
    "accuracy": (
        "You check facts, calculations, dates, names, and internal contradictions. "
        "You do not care about style. Approve only if you find no factual errors."
    ),
    "critic": (
        "You are the adversarial reviewer. Hunt for weaknesses, unsupported "
        "assumptions, logical gaps, and claims that would not survive an expert's "
        "scrutiny. Assume the output is flawed until proven otherwise."
    ),
    "evidence": (
        "You check whether claims are supported. Every non-obvious assertion should "
        "have a source, a calculation, or a stated assumption behind it. Flag anything "
        "presented as fact without support."
    ),
    "executive": (
        "You represent the person who asked for this. Is it useful, concise, "
        "actionable, and ready to use without further work? Penalise padding, "
        "hedging, and anything that makes the reader do the agent's job."
    ),
}


class JudgeOpinion(BaseModel):
    """The JSON shape we ask the model to return."""

    vote: Vote
    score: float = Field(ge=0, le=10)
    reason: str
    issues: list[str] = Field(default_factory=list)
    blocking: bool = False


SYSTEM_TEMPLATE = """You are an independent reviewer on a panel evaluating work done by an AI agent.

Your role: {role_name}
{role_description}

You will be given the task the agent was asked to do and the output it produced.
Judge the output against the task. You have not seen and will not see any other
reviewer's opinion. Be specific and brief.

Respond with ONLY a JSON object, no prose before or after, in exactly this shape:
{{
  "vote": "approve" or "revise",
  "score": <number from 0 to 10>,
  "reason": "<one or two sentences>",
  "issues": ["<specific problem>", ...],
  "blocking": <true if any issue makes the output unusable as-is, else false>
}}

Vote "approve" if the output meets the bar for your role. Vote "revise" if it does not.
A score of 8 or above should normally come with "approve"; 6 or below with "revise"."""


def build_system_prompt(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}. Known roles: {sorted(ROLES)}")
    return SYSTEM_TEMPLATE.format(role_name=role, role_description=ROLES[role])


def build_user_prompt(request: ReviewRequest) -> str:
    parts = [f"## Task\n{request.task}", f"## Agent output\n{request.output}"]
    if request.context:
        parts.insert(1, f"## Context\n{request.context}")
    for art in request.artifacts:
        parts.append(f"## Artifact: {art.name}\n{art.content}")
    return "\n\n".join(parts)


def parse_opinion(raw: str) -> JudgeOpinion:
    """Pull a JSON object out of model output, tolerating code fences and chatter."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in judge response:\n{raw}")
    try:
        return JudgeOpinion.model_validate(json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Judge returned malformed JSON: {exc}\n---\n{raw}") from exc


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------


class Judge(ABC):
    """One reviewer: a role plus a model that plays it."""

    provider: str = "unknown"

    def __init__(self, role: str, model: str):
        self.role = role
        self.model = model
        self.system_prompt = build_system_prompt(role)

    @property
    def name(self) -> str:
        return f"{self.role}/{self.provider}"

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send prompts to the model, return its raw text reply."""

    def review(self, request: ReviewRequest) -> Review:
        raw = self.complete(self.system_prompt, build_user_prompt(request))
        opinion = parse_opinion(raw)
        return Review(
            judge=self.name,
            model=self.model,
            vote=opinion.vote,
            score=opinion.score,
            reason=opinion.reason,
            issues=opinion.issues,
            blocking=opinion.blocking,
        )
