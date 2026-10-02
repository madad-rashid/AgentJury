"""OpenRouter presets must fail before constructing a transport or dispatching."""

import pytest

from agentjury.judges.compatible import CompatibleJudge, _router_model, openrouter_judge
from agentjury.judges.openrouter import OpenRouterJudge
from test_compatible_judge import fake_openai


@pytest.mark.parametrize("route", ["native", "sdk", "direct_sdk"])
@pytest.mark.parametrize("model", [
    "google/gemini-2.0-flash-001@preset/your-preset-slug",
    "openai/gpt-4:free@preset/other",
    "@preset/your-preset-slug",
    "openrouter/auto",
    "vendor/model/extra",
    "vendor/model%40preset%2Fname",
])
def test_nonfixed_model_rejected_before_transport(monkeypatch, fake_openai, route, model):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    import agentjury.judges.openrouter as native
    constructed = []
    monkeypatch.setattr(native, "build_opener", lambda *args: constructed.append(True))
    with pytest.raises(ValueError, match="model"):
        if route == "native":
            OpenRouterJudge("accuracy", model)
        elif route == "sdk":
            openrouter_judge("accuracy", model)
        else:
            CompatibleJudge("accuracy", model, route="openrouter",
                            base_url="https://openrouter.ai/api/v1",
                            api_key="offline-test-key", provider="google")
    assert constructed == []
    assert fake_openai.kwargs is None
    assert fake_openai.calls == []


@pytest.mark.parametrize("model", [
    "google/gemini-2.0-flash-001", "meta-llama/llama-3.1-405b-instruct:free",
    "qwen/qwen3-30b-a3b:thinking", "openai/gpt-4o:extended:nitro",
])
def test_fixed_model_and_variants_preserved(model):
    assert _router_model(model) == model.split(":", 1)[0]


@pytest.mark.parametrize("route", ["compatible", "ollama"])
def test_other_routes_keep_their_model_identifier_policy(fake_openai, route):
    judge = CompatibleJudge("accuracy", "custom/model@preset/name", route=route,
                            base_url="http://localhost:11434/v1", api_key=None,
                            provider=route)
    assert judge.model == "custom/model@preset/name"
