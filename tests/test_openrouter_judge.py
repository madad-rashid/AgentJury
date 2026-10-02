"""OpenRouter adapter contracts, tested against a local HTTP server."""

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentjury import Panel, ReviewRequest
from agentjury.judges import FakeJudge

OPINION = json.dumps({"vote": "approve", "score": 9, "reason": "Correct.", "findings": []})
REQUEST = ReviewRequest(task="Add 2 + 2", output="4")


def response(model="openai/test-model", content=OPINION, **extra):
    return {"id": "gen-test", "model": model, "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "finish_reason": "stop", "native_finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}, **extra}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-real-secret")
    state = {"requests": [], "responses": {}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.path, body, dict(self.headers)))
            result = state["responses"].get(body["model"], [(200, response(body["model"]))])
            status, payload = result.pop(0)
            data = json.dumps(payload).encode()
            self.send_response(status)
            if state.get("redirect"):
                self.send_header("Location", state["redirect"])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if state.get("delay"):
                threading.Event().wait(state["delay"])
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            state["redirected_headers"] = dict(self.headers)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{httpd.server_port}/api/v1/chat/completions"
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def make_judge(server, monkeypatch, role="accuracy", model="openai/test-model", **kwargs):
    mod = importlib.import_module("agentjury.judges.openrouter")
    monkeypatch.setattr(mod, "API_URL", server["url"])
    return mod.OpenRouterJudge(role, model, **kwargs)


def test_request_auth_blind_prompts_and_telemetry(server, monkeypatch):
    judge = make_judge(server, monkeypatch)
    review = judge.review(REQUEST)
    assert (review.provider, review.model, review.vote) == ("openai", "openai/test-model", "approve")
    assert (review.tokens_in, review.tokens_out, review.response_id) == (20, 10, "gen-test")
    path, body, headers = server["requests"][0]
    assert path == "/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer test-key-not-a-real-secret"
    assert body["stream"] is False and body["model"] == "openai/test-model"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "<<<BEGIN AGENT OUTPUT" in body["messages"][1]["content"]
    assert "models" not in body and "route" not in body
    assert review.params["transport"] == "openrouter"
    assert "test-key-not-a-real-secret" not in review.model_dump_json()
    assert review.observed_model == "openai/test-model"


def test_separate_model_authors_count_separately(server, monkeypatch):
    panel = Panel([make_judge(server, monkeypatch),
                   make_judge(server, monkeypatch, "critic", "anthropic/test-model")])
    verdict = panel.review(REQUEST)
    assert verdict.status == "verified" and verdict.diversity == 1
    assert {r.provider for r in verdict.reviews} == {"openai", "anthropic"}


def test_same_author_does_not_create_extra_diversity(server, monkeypatch):
    panel = Panel([make_judge(server, monkeypatch), FakeJudge("critic", provider="openai")])
    verdict = panel.review(REQUEST)
    assert verdict.status == "verified" and verdict.diversity == 0.5


def test_lost_author_fails_provider_floor_even_with_quorum(server, monkeypatch):
    server["responses"]["anthropic/test-model"] = [(503, {"error": {"message": "busy"}})] * 2
    panel = Panel([make_judge(server, monkeypatch),
                   make_judge(server, monkeypatch, "executive"),
                   make_judge(server, monkeypatch, "critic", "anthropic/test-model")])
    verdict = panel.review(REQUEST)
    assert verdict.responded == verdict.quorum == 2
    assert verdict.status == "insufficient_jury" and len(verdict.errors) == 1


def test_http_error_retries_once(server, monkeypatch):
    server["responses"]["openai/test-model"] = [(429, {"error": "limit"}), (200, response())]
    assert make_judge(server, monkeypatch).review(REQUEST).vote == "approve"
    assert len(server["requests"]) == 2


def test_json_opinion_repair_and_total_tokens(server, monkeypatch):
    server["responses"]["openai/test-model"] = [(200, response(content="bad")), (200, response())]
    review = make_judge(server, monkeypatch).review(REQUEST)
    assert (review.tokens_in, review.tokens_out) == (40, 20)
    assert "previous reply had invalid JSON" in server["requests"][1][1]["messages"][1]["content"]


@pytest.mark.parametrize("payload", [
    {"error": {"code": 500, "message": "busy"}},
    response(model="anthropic/test-model"),
    response(model="openai/different-model"),
    response(choices=[]),
    response(choices=[{"finish_reason": "length", "message": {"content": OPINION}}]),
    response(choices=[{"finish_reason": "stop", "message": {"content": None}}]),
    response(choices=[{"finish_reason": "stop", "message": {"content": OPINION}, "error": {"code": 500}}]),
    [],
])
def test_malformed_or_mismatched_response_cannot_vote(server, monkeypatch, payload):
    server["responses"]["openai/test-model"] = [(200, payload)] * 2
    verdict = Panel([make_judge(server, monkeypatch)]).review(REQUEST)
    assert verdict.status == "insufficient_jury" and verdict.responded == 0
    assert len(verdict.errors) == 1


def test_variant_preserves_request_and_canonical_model(server, monkeypatch):
    server["responses"]["openai/test-model:free"] = [(200, response())]
    review = make_judge(server, monkeypatch, model="openai/test-model:free").review(REQUEST)
    assert review.model == "openai/test-model" and review.provider == "openai"
    assert review.params["requested_model"] == "openai/test-model:free"
    assert server["requests"][0][1]["model"] == "openai/test-model:free"
    assert review.observed_model == "openai/test-model"


def test_missing_usage_is_unknown(server, monkeypatch):
    server["responses"]["openai/test-model"] = [(200, response(usage=None))]
    review = make_judge(server, monkeypatch).review(REQUEST)
    assert review.tokens_in is None and review.tokens_out is None


def test_timeout_records_failed_judge(server, monkeypatch):
    server["delay"] = 0.2
    judge = make_judge(server, monkeypatch, timeout=0.03)
    judge.retries = 0
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.status == "insufficient_jury" and "TimeoutError" in verdict.errors[0]


def test_redirect_does_not_forward_api_key(server, monkeypatch):
    server["responses"]["openai/test-model"] = [(302, {})] * 2
    server["redirect"] = server["url"].replace("chat/completions", "other")
    verdict = Panel([make_judge(server, monkeypatch)]).review(REQUEST)
    assert verdict.status == "insufficient_jury"
    assert "redirected_headers" not in server


@pytest.mark.parametrize("model", ["", "model-only", "openrouter/auto", "openrouter/free",
                                   "~openai/latest", "@preset", "openai/", " openai/test-model"])
def test_requires_fixed_author_model_slug(server, monkeypatch, model):
    monkeypatch.delenv("AGENTJURY_OPENROUTER_MODEL", raising=False)
    with pytest.raises(ValueError, match="model"):
        make_judge(server, monkeypatch, model=model)


def test_missing_key_has_setup_error(server, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        make_judge(server, monkeypatch)


def test_secret_does_not_affect_identity(server, monkeypatch):
    first = make_judge(server, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "different-test-key")
    second = make_judge(server, monkeypatch)
    assert first.config_id == second.config_id
    variant = make_judge(server, monkeypatch, model="openai/test-model:free")
    assert first.config_id != variant.config_id


def test_cli_explicit_models_keep_variant_colon(server, monkeypatch):
    make_judge(server, monkeypatch)
    from agentjury.cli import build_panel
    server["responses"]["openai/test-model:free"] = [(200, response())]
    verdict = build_panel("accuracy:openrouter:openai/test-model:free,critic:openrouter:anthropic/test-model").review(REQUEST)
    assert verdict.status == "verified" and verdict.diversity == 1


def test_environment_model_used_for_short_spec(server, monkeypatch):
    make_judge(server, monkeypatch)
    from agentjury.cli import build_panel
    monkeypatch.setenv("AGENTJURY_OPENROUTER_MODEL", "google/test-model")
    verdict = build_panel("accuracy:openrouter").review(REQUEST)
    assert verdict.reviews[0].provider == "google"


def test_hermes_accepts_explicit_openrouter_models(server, monkeypatch):
    make_judge(server, monkeypatch)
    from test_hermes_plugin import load_plugin
    load_plugin()
    from hermes_agentjury.jury import Settings, build_panel
    verdict = build_panel(Settings(panel="accuracy:openrouter:openai/test-model,critic:openrouter:anthropic/test-model")).review(REQUEST)
    assert verdict.status == "verified" and verdict.diversity == 1


def test_endpoint_is_not_saved(server, monkeypatch):
    review = make_judge(server, monkeypatch).review(REQUEST)
    assert "endpoint_hash" in review.params
    assert server["url"] not in review.model_dump_json()


def test_variant_model_names_cannot_hide_a_different_model(server, monkeypatch):
    server["responses"]["openai/test-model:free"] = [(200, response(model="openai/test-model:other"))]
    judge = make_judge(server, monkeypatch, model="openai/test-model:free")
    judge.retries = 0
    assert Panel([judge]).review(REQUEST).responded == 0


def test_invalid_usage_cannot_expose_provider_data(server, monkeypatch):
    server["responses"]["openai/test-model"] = [(200, response(usage={"prompt_tokens": "SECRET_MARKER"}))]
    judge = make_judge(server, monkeypatch)
    judge.retries = 0
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.responded == 0
    assert "SECRET_MARKER" not in verdict.model_dump_json()


@pytest.mark.parametrize("response_id", [{"secret": "SECRET_MARKER"}, ["SECRET_MARKER"], 42])
def test_invalid_response_id_cannot_expose_provider_data(server, monkeypatch, response_id):
    server["responses"]["openai/test-model"] = [(200, response(id=response_id))]
    judge = make_judge(server, monkeypatch)
    judge.retries = 0
    verdict = Panel([judge]).review(REQUEST)
    assert verdict.responded == 0
    assert "SECRET_MARKER" not in verdict.model_dump_json()
