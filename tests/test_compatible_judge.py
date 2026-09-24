"""OpenAI-compatible routes keep jury identity and errors auditable."""

import json
import sys
import types

import pytest

from agentjury import Panel, ReviewRequest


@pytest.fixture
def fake_openai(monkeypatch):
    state = types.SimpleNamespace(kwargs=None, calls=[], error=None, texts=[])

    def create(**kwargs):
        state.calls.append(kwargs)
        if state.error:
            raise state.error
        opinion = {"vote": "approve", "score": 9, "reason": "Correct.", "findings": []}
        content = state.texts.pop(0) if state.texts else json.dumps(opinion)
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        return types.SimpleNamespace(choices=[choice], usage=usage, id="resp-1")

    class Client:
        def __init__(self, **kwargs):
            state.kwargs = kwargs
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    module = types.ModuleType("openai")
    module.OpenAI = Client
    monkeypatch.setitem(sys.modules, "openai", module)
    return state


def test_openrouter_uses_one_key_and_vendor_identity(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    from agentjury.judges import openrouter_judge

    judge = openrouter_judge("accuracy", "anthropic/claude-sonnet-4")
    review = judge.review(ReviewRequest(task="Check this", output="Answer"))

    assert judge.provider == "anthropic"
    assert review.model == "anthropic/claude-sonnet-4"
    assert review.judge == "accuracy/openrouter/anthropic/claude-sonnet-4"
    assert review.params["route"] == "openrouter"
    assert fake_openai.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert fake_openai.kwargs["api_key"] == "test-router-key"
    assert fake_openai.kwargs["max_retries"] == 0
    assert fake_openai.calls[0]["model"] == "anthropic/claude-sonnet-4"
    assert [m["role"] for m in fake_openai.calls[0]["messages"]] == ["system", "user"]
    assert "test-router-key" not in review.model_dump_json()
    assert review.tokens_in == 11 and review.tokens_out == 7
    assert review.response_id == "resp-1"


def test_ollama_uses_local_endpoint_without_user_key(fake_openai):
    from agentjury.judges import ollama_judge

    review = ollama_judge("critic", "qwen3:8b").review(
        ReviewRequest(task="Check this", output="Answer"))

    assert review.provider == "ollama"
    assert review.model == "qwen3:8b"
    assert fake_openai.kwargs["base_url"] == "http://127.0.0.1:11434/v1"
    assert fake_openai.kwargs["api_key"]
    assert "endpoint_hash" in review.params
    assert "127.0.0.1" not in review.model_dump_json()


def test_custom_endpoint_can_omit_key(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1/")
    monkeypatch.delenv("AGENTJURY_COMPATIBLE_API_KEY", raising=False)
    review = compatible_judge("accuracy", "local-model").review(
        ReviewRequest(task="Check this", output="Answer"))

    assert fake_openai.kwargs["base_url"] == "http://localhost:1234/v1"
    assert fake_openai.kwargs["api_key"]
    assert review.provider == "compatible"
    assert review.params["route"] == "compatible"
    assert "localhost:1234" not in review.model_dump_json()


@pytest.mark.parametrize("url", [
    "ftp://host/v1",
    "http://user:pass@host/v1",
    "http://host/v1?token=x",
    "http://host/v1#fragment",
])
def test_custom_endpoint_rejects_unsafe_url(monkeypatch, fake_openai, url):
    from agentjury.judges import compatible_judge

    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", url)
    with pytest.raises(ValueError, match="URL"):
        compatible_judge("accuracy", "local-model")


def test_openrouter_requires_key(monkeypatch, fake_openai):
    from agentjury.judges import openrouter_judge

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        openrouter_judge("accuracy", "openai/gpt-4o")


def test_custom_endpoint_requires_url(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.delenv("AGENTJURY_COMPATIBLE_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="AGENTJURY_COMPATIBLE_BASE_URL"):
        compatible_judge("accuracy", "local-model")


@pytest.mark.parametrize("model", ["~openai/gpt-latest", "auto", "/gpt-4o", "openai/"])
def test_openrouter_rejects_ambiguous_model(monkeypatch, fake_openai, model):
    from agentjury.judges import openrouter_judge

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    with pytest.raises(ValueError, match="vendor/model"):
        openrouter_judge("accuracy", model)


def test_endpoint_changes_configuration_identity(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    first = compatible_judge("accuracy", "local-model")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:5678/v1")
    second = compatible_judge("accuracy", "local-model")
    assert first.config_id != second.config_id


def test_transport_error_hides_provider_message(monkeypatch, fake_openai):
    from agentjury.judges import openrouter_judge

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    judge = openrouter_judge("accuracy", "openai/gpt-4o")
    fake_openai.error = RuntimeError("SECRET_MARKER")
    with pytest.raises(RuntimeError) as raised:
        judge.complete("system", "user")
    assert "openrouter" in str(raised.value)
    assert "openai/gpt-4o" in str(raised.value)
    assert "SECRET_MARKER" not in str(raised.value)


def test_connection_failure_reduces_jury(monkeypatch, fake_openai):
    from agentjury.judges import ollama_judge

    judge = ollama_judge("accuracy", "qwen3:8b")
    fake_openai.error = ConnectionError("offline")
    verdict = Panel([judge]).review(ReviewRequest(task="Check", output="Answer"))
    assert verdict.status == "insufficient_jury"
    assert "ollama" in verdict.errors[0]
    assert "qwen3:8b" in verdict.errors[0]
    assert "127.0.0.1" not in verdict.model_dump_json()


def test_malformed_response_gets_one_repair_call(fake_openai):
    from agentjury.judges import ollama_judge

    valid = json.dumps({"vote": "approve", "score": 9, "reason": "Correct.", "findings": []})
    fake_openai.texts = ["not JSON", valid]
    review = ollama_judge("accuracy", "qwen3:8b").review(
        ReviewRequest(task="Check", output="Answer"))
    assert review.vote == "approve"
    assert len(fake_openai.calls) == 2


def test_persistent_malformed_response_reduces_jury(fake_openai):
    from agentjury.judges import ollama_judge

    fake_openai.texts = ["not JSON", "still not JSON"]
    verdict = Panel([ollama_judge("accuracy", "qwen3:8b")]).review(
        ReviewRequest(task="Check", output="Answer"))
    assert verdict.status == "insufficient_jury"
    assert len(fake_openai.calls) == 2
    assert "ValueError" in verdict.errors[0]
