from .base import ROLES, Judge, JudgeOpinion, parse_opinion
from .fake import FakeJudge

__all__ = ["ROLES", "Judge", "JudgeOpinion", "parse_opinion", "FakeJudge"]


def openai_judge(role: str, model: str | None = None):
    from .openai_judge import OpenAIJudge
    return OpenAIJudge(role, model) if model else OpenAIJudge(role)


def anthropic_judge(role: str, model: str | None = None):
    from .anthropic_judge import AnthropicJudge
    return AnthropicJudge(role, model) if model else AnthropicJudge(role)
