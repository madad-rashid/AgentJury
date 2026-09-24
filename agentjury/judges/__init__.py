from .base import ROLES, RUBRIC_VERSION, Completion, Judge, JudgeOpinion, load_roles, parse_opinion, register_roles
from .fake import FakeJudge

__all__ = ["ROLES", "RUBRIC_VERSION", "Completion", "Judge", "JudgeOpinion", "load_roles", "parse_opinion", "register_roles", "FakeJudge", "openrouter_judge", "ollama_judge", "compatible_judge"]


def openai_judge(role: str, model: str | None = None):
    from .openai_judge import OpenAIJudge
    return OpenAIJudge(role, model) if model else OpenAIJudge(role)


def anthropic_judge(role: str, model: str | None = None):
    from .anthropic_judge import AnthropicJudge
    return AnthropicJudge(role, model) if model else AnthropicJudge(role)


def openrouter_judge(role: str, model: str):
    from .compatible import openrouter_judge as make_judge
    return make_judge(role, model)


def ollama_judge(role: str, model: str):
    from .compatible import ollama_judge as make_judge
    return make_judge(role, model)


def compatible_judge(role: str, model: str):
    from .compatible import compatible_judge as make_judge
    return make_judge(role, model)
