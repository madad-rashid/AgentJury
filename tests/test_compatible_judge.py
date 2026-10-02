"""OpenAI-compatible routes keep jury identity and errors auditable."""

import json
import sys
import types

import pytest
from openai import DefaultHttpxClient
from openai.types.chat import ChatCompletion

from agentjury import Panel, ReviewRequest


@pytest.fixture
def fake_openai(monkeypatch):
    state = types.SimpleNamespace(kwargs=None, calls=[], error=None, texts=[], response=None)

    def create(**kwargs):
        state.calls.append(kwargs)
        if state.response is not None:
            return state.response
        if state.error:
            raise state.error
        opinion = {"vote": "approve", "score": 9, "reason": "Correct.", "findings": []}
        content = state.texts.pop(0) if state.texts else json.dumps(opinion)
        return ChatCompletion.model_validate({
            "id": "resp-1", "object": "chat.completion", "created": 1,
            "model": kwargs["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })

    class Client:
        def __init__(self, **kwargs):
            state.kwargs = kwargs
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    module = types.ModuleType("openai")
    module.OpenAI = Client
    module.DefaultHttpxClient = DefaultHttpxClient
    monkeypatch.setitem(sys.modules, "openai", module)
    return state


def test_openrouter_uses_one_key_and_vendor_identity(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    from agentjury.judges.compatible import openrouter_judge

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
    from agentjury.judges.compatible import ollama_judge

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
    from agentjury.judges.compatible import openrouter_judge

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        openrouter_judge("accuracy", "openai/gpt-4o")


def test_custom_endpoint_requires_url(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.delenv("AGENTJURY_COMPATIBLE_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="AGENTJURY_COMPATIBLE_BASE_URL"):
        compatible_judge("accuracy", "local-model")


@pytest.mark.parametrize("model", [
    "~openai/gpt-latest", "auto", "/gpt-4o", "openai/",
    "openrouter/auto", "openrouter/free", "openrouter/pareto-code",
])
def test_openrouter_rejects_ambiguous_model(monkeypatch, fake_openai, model):
    from agentjury.judges.compatible import openrouter_judge

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    with pytest.raises(ValueError, match="vendor/model"):
        openrouter_judge("accuracy", model)


def test_same_ollama_endpoint_cannot_count_as_two_providers(monkeypatch, fake_openai):
    from agentjury.judges.compatible import compatible_judge, ollama_judge
    from agentjury.judges.compatible import OLLAMA_URL
    from agentjury.judges import FakeJudge

    monkeypatch.setenv("AGENTJURY_OLLAMA_BASE_URL", OLLAMA_URL)
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", OLLAMA_URL + "/")
    verdict = Panel([
        ollama_judge("accuracy", "qwen3:8b"),
        compatible_judge("critic", "qwen3:8b"),
        FakeJudge("executive", provider="anthropic", fail_times=2),
    ]).review(ReviewRequest(task="Check", output="Answer"))

    assert [review.params["route"] for review in verdict.reviews] == ["ollama", "compatible"]
    assert [review.provider for review in verdict.reviews] == ["ollama", "ollama"]
    assert verdict.status == "insufficient_jury"


def test_custom_endpoint_ignores_unselected_ollama_config(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AGENTJURY_OLLAMA_BASE_URL", "invalid-url")
    assert compatible_judge("accuracy", "local-model").provider == "compatible"


def test_endpoint_changes_configuration_identity(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge

    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    first = compatible_judge("accuracy", "local-model")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:5678/v1")
    second = compatible_judge("accuracy", "local-model")
    assert first.config_id != second.config_id


def test_transport_error_hides_provider_message(monkeypatch, fake_openai):
    from agentjury.judges.compatible import openrouter_judge

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    judge = openrouter_judge("accuracy", "openai/gpt-4o")
    fake_openai.error = RuntimeError("SECRET_MARKER")
    with pytest.raises(RuntimeError) as raised:
        judge.complete("system", "user")
    assert "openrouter" in str(raised.value)
    assert "openai/gpt-4o" in str(raised.value)
    assert "SECRET_MARKER" not in str(raised.value)


def test_connection_failure_reduces_jury(monkeypatch, fake_openai):
    from agentjury.judges.compatible import ollama_judge

    judge = ollama_judge("accuracy", "qwen3:8b")
    fake_openai.error = ConnectionError("offline")
    verdict = Panel([judge]).review(ReviewRequest(task="Check", output="Answer"))
    assert verdict.status == "insufficient_jury"
    assert "ollama" in verdict.errors[0]
    assert "qwen3:8b" in verdict.errors[0]
    assert "127.0.0.1" not in verdict.model_dump_json()


def test_malformed_response_gets_one_repair_call(fake_openai):
    from agentjury.judges.compatible import ollama_judge

    valid = json.dumps({"vote": "approve", "score": 9, "reason": "Correct.", "findings": []})
    fake_openai.texts = ["not JSON", valid]
    review = ollama_judge("accuracy", "qwen3:8b").review(
        ReviewRequest(task="Check", output="Answer"))
    assert review.vote == "approve"
    assert len(fake_openai.calls) == 2


def test_persistent_malformed_response_reduces_jury(fake_openai):
    from agentjury.judges.compatible import ollama_judge

    fake_openai.texts = ["not JSON", "still not JSON"]
    verdict = Panel([ollama_judge("accuracy", "qwen3:8b")]).review(
        ReviewRequest(task="Check", output="Answer"))
    assert verdict.status == "insufficient_jury"
    assert len(fake_openai.calls) == 2
    assert "ValueError" in verdict.errors[0]


@pytest.mark.parametrize("finish_reason", [None, "length", "content_filter", "tool_calls"])
def test_unfinished_sdk_response_cannot_vote(fake_openai, finish_reason):
    from agentjury.judges.compatible import ollama_judge
    fake_openai.response = types.SimpleNamespace(model="qwen3:8b", choices=[types.SimpleNamespace(finish_reason=finish_reason, message=types.SimpleNamespace(content='{"vote":"approve","score":9,"reason":"ok"}'))], usage=None)
    with pytest.raises(RuntimeError):
        ollama_judge("accuracy", "qwen3:8b").complete("system", "user")


def test_wrong_sdk_model_cannot_vote(fake_openai):
    from agentjury.judges.compatible import ollama_judge
    fake_openai.response = types.SimpleNamespace(model="different-model", choices=[types.SimpleNamespace(finish_reason="stop", message=types.SimpleNamespace(content="ok"))], usage=None)
    with pytest.raises(RuntimeError):
        ollama_judge("accuracy", "qwen3:8b").complete("system", "user")


@pytest.mark.parametrize("native,compatible", [
    ("HTTP://LOCALHOST:80/", "http://localhost/v1/"),
    ("https://LocalHost:443", "https://localhost/v1"),
    ("http://localhost:11434", "http://LOCALHOST:11434/v1/"),
])
def test_native_origin_is_same_as_compatible_v1(monkeypatch, fake_openai, native, compatible):
    from agentjury.judges import compatible_judge
    monkeypatch.delenv("AGENTJURY_OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("AGENTJURY_OLLAMA_URL", native)
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", compatible)
    assert compatible_judge("accuracy", "local-model").provider == "ollama"


def test_endpoint_normalization_keeps_configuration_identity(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "HTTP://Example.COM:80/v1/")
    first = compatible_judge("accuracy", "model")
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://example.com/v1")
    assert first.config_id == compatible_judge("accuracy", "model").config_id


def test_sdk_transport_does_not_follow_redirects(monkeypatch, fake_openai):
    from agentjury.judges import compatible_judge
    monkeypatch.setenv("AGENTJURY_COMPATIBLE_BASE_URL", "http://localhost:1234/v1")
    compatible_judge("accuracy", "model")
    assert fake_openai.kwargs["http_client"].follow_redirects is False


def test_sdk_native_incomplete_reason_cannot_vote(fake_openai):
    from agentjury.judges.compatible import ollama_judge
    fake_openai.response = types.SimpleNamespace(model="qwen3:8b", choices=[types.SimpleNamespace(
        finish_reason="stop", native_finish_reason="length", message=types.SimpleNamespace(content="ok"))])
    with pytest.raises(RuntimeError):
        ollama_judge("accuracy", "qwen3:8b").complete("system", "user")


def test_invalid_sdk_usage_cannot_expose_provider_data(fake_openai):
    from agentjury.judges.compatible import ollama_judge
    fake_openai.response = types.SimpleNamespace(model="qwen3:8b", choices=[types.SimpleNamespace(
        finish_reason="stop", message=types.SimpleNamespace(content="ok"))],
        usage=types.SimpleNamespace(prompt_tokens="SECRET_MARKER", completion_tokens=1))
    with pytest.raises(RuntimeError) as raised:
        ollama_judge("accuracy", "qwen3:8b").complete("system", "user")
    assert "SECRET_MARKER" not in str(raised.value)


@pytest.mark.parametrize("response_id", [{"secret": "SECRET_MARKER"}, ["SECRET_MARKER"], 42])
def test_invalid_sdk_response_id_cannot_expose_provider_data(fake_openai, response_id):
    from agentjury.judges.compatible import ollama_judge
    content = json.dumps({"vote": "approve", "score": 9, "reason": "ok", "findings": []})
    fake_openai.response = types.SimpleNamespace(model="qwen3:8b", choices=[types.SimpleNamespace(
        finish_reason="stop", message=types.SimpleNamespace(content=content))], usage=None, id=response_id)
    judge = ollama_judge("accuracy", "qwen3:8b")
    judge.retries = 0
    verdict = Panel([judge]).review(ReviewRequest(task="Check", output="Answer"))
    assert verdict.responded == 0
    assert "SECRET_MARKER" not in verdict.model_dump_json()
