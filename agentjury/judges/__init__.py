from .base import CODE_ROLES, ROLES, RUBRIC_VERSION, Completion, Judge, JudgeOpinion, load_roles, parse_opinion, parse_roles, register_roles
from .fake import FakeJudge
from .openai_judge import OpenAIJudge
from .anthropic_judge import AnthropicJudge

__all__ = ["CODE_ROLES", "ROLES", "RUBRIC_VERSION", "parse_roles", "Completion", "Judge", "JudgeOpinion", "load_roles", "parse_opinion", "register_roles", "FakeJudge", "openai_judge", "anthropic_judge", "openrouter_judge", "ollama_judge", "compatible_judge"]


def openai_judge(role: str, model: str | None = None):
    return OpenAIJudge(role, model) if model else OpenAIJudge(role)


def anthropic_judge(role: str, model: str | None = None):
    return AnthropicJudge(role, model) if model else AnthropicJudge(role)


def openrouter_judge(role: str, model: str | None = None):
    from .openrouter import OpenRouterJudge
    return OpenRouterJudge(role, model)


def ollama_judge(role: str, model: str | None = None):
    from .ollama import OllamaJudge
    return OllamaJudge(role, model)


def compatible_judge(role: str, model: str):
    from .compatible import compatible_judge as make_judge
    return make_judge(role, model)
