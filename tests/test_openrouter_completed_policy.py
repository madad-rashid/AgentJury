"""Provider-specific completion normalization without relaxing other guards."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from agentjury.judges.openrouter import OpenRouterJudge
from agentjury.judges.compatible import CompatibleJudge

MODEL = "openai/gpt-6.1-sol"
MESSAGES = [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}]


def response(model=MODEL, provider="OpenAI", finish="stop", native="completed", content="synthetic opinion", **extra):
    data = {"id": "gen-offline", "model": model, "provider": provider, "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "finish_reason": finish, "native_finish_reason": native,
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"cost": 0.0002, "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
    data.update(extra)
    return data


def judge(monkeypatch, kind, data, model=MODEL):
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-dummy")
    if kind == "native":
        value = OpenRouterJudge("accuracy", model)
        value._opener = SimpleNamespace(open=lambda *a, **k: io.BytesIO(json.dumps(data).encode()))
    else:
        value = CompatibleJudge("accuracy", model, route="openrouter" if kind == "sdk" else "compatible",
                                base_url="https://openrouter.ai/api/v1" if kind == "sdk" else "https://example.invalid/v1",
                                api_key="offline-dummy", provider="openai" if kind == "sdk" else "compatible")
        client = value._client
        value._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: ChatCompletion.model_validate(data))))
        client.close()
    return value


@pytest.mark.parametrize("kind", ["native", "sdk"])
def test_openrouter_openai_completed_is_a_complete_message(monkeypatch, kind):
    value = judge(monkeypatch, kind, response())
    completion = value.complete("system", "user")
    assert completion.text == "synthetic opinion" and completion.observed_model == MODEL
    assert value.params["completion_policy"] == "openai-completed-v1"


@pytest.mark.parametrize("kind", ["native", "sdk"])
@pytest.mark.parametrize("changes", [
    {"provider": None}, {"provider": "Anthropic"}, {"provider": "Azure"}, {"provider": "openai"},
    {"finish": "length"}, {"finish": "error"}, {"finish": "content_filter"},
    {"native": "failed"}, {"native": "incomplete"}, {"native": "cancelled"},
    {"native": "in_progress"}, {"native": "queued"}, {"native": "unknown"},
    {"native": "length"}, {"native": "max_tokens"}, {"native": None},
    {"content": ""}, {"content": None}, {"model": "openai/other-model"},
    {"error": {"message": "failure"}},
    {"native": "refusal"}, {"choices": []}, {"choices": [{}, {}]},
    {"choices": [{"finish_reason": "stop", "native_finish_reason": "completed", "error": {"code": 500}, "message": {"content": "text"}}]},
])
def test_completed_mapping_does_not_certify_invalid_responses(monkeypatch, kind, changes):
    with pytest.raises(RuntimeError):
        judge(monkeypatch, kind, response(**changes)).complete("system", "user")


@pytest.mark.parametrize("kind", ["native", "sdk"])
def test_completed_is_not_enabled_for_anthropic_models(monkeypatch, kind):
    model = "anthropic/claude-sonnet-5.5"
    with pytest.raises(RuntimeError):
        judge(monkeypatch, kind, response(model=model, provider="OpenAI"), model).complete("system", "user")


def test_generic_compatible_endpoint_does_not_gain_completed_mapping(monkeypatch):
    with pytest.raises(RuntimeError):
        judge(monkeypatch, "generic", response()).complete("system", "user")


def test_capped_harness_accepts_only_the_same_qualified_mapping(tmp_path):
    spec = importlib.util.spec_from_file_location("completed_harness", Path(__file__).parents[1]/"experiments/openrouter/capped_transport.py")
    h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
    raw = json.dumps(response()).encode()
    ledger = h.Ledger(tmp_path/"journal.json")
    inner = SimpleNamespace(open=lambda *a, **k: io.BytesIO(raw))
    transport = h.CappedTransport(inner, ledger, "synthetic", MODEL, MESSAGES, "repair", lambda a,b:a==b)
    from urllib.request import Request
    req = Request("https://openrouter.ai/api/v1/chat/completions", method="POST",
                  data=json.dumps({"model": MODEL, "messages": MESSAGES, "stream": False}).encode())
    assert transport.open(req,90).read() == raw
    assert ledger.calls[0]["diagnostic"]["native_finish_reason"] == "completed"


@pytest.mark.parametrize("kind", ["native", "sdk"])
def test_completion_policy_versions_reviewer_identity(monkeypatch, kind):
    value = judge(monkeypatch, kind, response())
    new_identity = value.config_id
    del value.params["completion_policy"]
    assert value.config_id != new_identity
