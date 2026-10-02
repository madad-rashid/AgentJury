"""Exercise the local adapter against a real HTTP server, without model calls."""

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentjury import Panel, ReviewRequest
from agentjury.judges import FakeJudge


OPINION = json.dumps({"vote": "approve", "score": 9, "reason": "Correct.", "findings": []})


def reply(content=OPINION, **extra):
    return {"model": "local-model", "message": {"role": "assistant", "content": content},
            "done": True, "prompt_eval_count": 20, "eval_count": 10, **extra}


@pytest.fixture
def server():
    state = {"responses": [], "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.path, body, dict(self.headers)))
            status, response = state["responses"].pop(0)
            if callable(response):
                response = response(body)
            data = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if state.get("delay"):
                threading.Event().wait(state["delay"])
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when the timeout test closes the client socket.

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def make_judge(server, **kwargs):
    module = importlib.import_module("agentjury.judges.ollama")
    return module.OllamaJudge("accuracy", "local-model", base_url=server["url"], **kwargs)


def test_native_chat_has_blind_prompts_and_telemetry(server, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    server["responses"] = [(200, reply())]
    review = make_judge(server).review(ReviewRequest(task="Add 2 + 2", output="4"))
    assert (review.provider, review.model, review.vote, review.score) == ("ollama", "local-model", "approve", 9)
    assert (review.tokens_in, review.tokens_out, review.response_id) == (20, 10, None)
    path, body, headers = server["requests"][0]
    assert path == "/api/chat"
    assert body["model"] == "local-model"
    assert body["stream"] is False and body["format"] == "json"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "<<<BEGIN AGENT OUTPUT" in body["messages"][1]["content"]
    assert "Authorization" not in headers


def test_http_failure_retries_then_succeeds(server):
    server["responses"] = [(503, {"error": "busy"}), (200, reply())]
    assert make_judge(server).review(ReviewRequest(task="Add", output="4")).vote == "approve"
    assert len(server["requests"]) == 2


def test_http_failure_after_retry_is_recorded(server):
    server["responses"] = [(404, {"error": "model not found"})] * 2
    verdict = Panel([make_judge(server)]).review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "insufficient_jury" and verdict.responded == 0
    assert "HTTPError" in verdict.errors[0]
    assert len(server["requests"]) == 2


def test_socket_timeout_fails_judge(server):
    server["responses"] = [(200, reply())]
    server["delay"] = 0.2
    judge = make_judge(server, timeout=0.03)
    judge.retries = 0
    verdict = Panel([judge]).review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "insufficient_jury" and verdict.responded == 0
    assert "TimeoutError" in verdict.errors[0]


def test_invalid_opinion_gets_one_repair_and_sums_tokens(server):
    server["responses"] = [(200, reply("not JSON")), (200, reply())]
    review = make_judge(server).review(ReviewRequest(task="Add", output="4"))
    assert (review.tokens_in, review.tokens_out) == (40, 20)
    assert "previous reply had invalid JSON" in server["requests"][1][1]["messages"][1]["content"]


@pytest.mark.parametrize("response", [
    {"error": "model unavailable"},
    {"done": False, "message": {"content": OPINION}},
    {"done": True, "message": {"content": None}},
    {"done": True},
    [],
])
def test_broken_transport_response_reduces_quorum(server, response):
    server["responses"] = [(200, response), (200, response)]
    panel = Panel([make_judge(server), FakeJudge("critic", provider="openai")])
    verdict = panel.review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "insufficient_jury"
    assert verdict.responded == 1 and len(verdict.errors) == 1


def test_persistently_invalid_opinion_fails_judge(server):
    server["responses"] = [(200, reply("bad")), (200, reply("still bad"))]
    verdict = Panel([make_judge(server)]).review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "insufficient_jury" and verdict.responded == 0


def test_missing_usage_stays_unknown(server):
    server["responses"] = [(200, {"model": "local-model", "done": True, "message": {"content": OPINION}})]
    review = make_judge(server).review(ReviewRequest(task="Add", output="4"))
    assert review.tokens_in is None and review.tokens_out is None


def test_endpoint_is_part_of_reviewer_identity(server):
    judge = make_judge(server)
    other = type(judge)("accuracy", "local-model", base_url="http://127.0.0.1:11434")
    assert judge.config_id != other.config_id


def test_different_local_models_still_share_one_provider(server):
    first = make_judge(server)
    second = type(first)("critic", "different-model", base_url=server["url"])
    server["responses"] = [(200, lambda body: reply(model=body["model"]))] * 2
    verdict = Panel([first, second]).review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "verified" and verdict.diversity == 0.5
    assert {r.provider for r in verdict.reviews} == {"ollama"}
    assert {r.model for r in verdict.reviews} == {"local-model", "different-model"}


def test_missing_model_has_setup_error(monkeypatch):
    monkeypatch.delenv("AGENTJURY_OLLAMA_MODEL", raising=False)
    module = importlib.import_module("agentjury.judges.ollama")
    with pytest.raises(ValueError, match="AGENTJURY_OLLAMA_MODEL"):
        module.OllamaJudge("accuracy")


def test_cli_uses_environment_model_and_endpoint(server, monkeypatch):
    from agentjury.cli import build_panel
    monkeypatch.setenv("AGENTJURY_OLLAMA_MODEL", "installed-model:latest")
    monkeypatch.setenv("AGENTJURY_OLLAMA_URL", server["url"])
    server["responses"] = [(200, reply(model="installed-model:latest"))]
    verdict = build_panel("accuracy:ollama").review(ReviewRequest(task="Add", output="4"))
    assert verdict.status == "verified"
    assert server["requests"][0][1]["model"] == "installed-model:latest"


def test_hermes_builds_local_panel(server, monkeypatch):
    from test_hermes_plugin import load_plugin
    load_plugin()
    from hermes_agentjury.jury import Settings, build_panel
    monkeypatch.setenv("AGENTJURY_OLLAMA_MODEL", "local-model")
    monkeypatch.setenv("AGENTJURY_OLLAMA_URL", server["url"])
    server["responses"] = [(200, reply()), (200, reply())]
    verdict = build_panel(Settings(panel="accuracy:ollama,critic:ollama")).review(
        ReviewRequest(task="Add", output="4"))
    assert verdict.status == "verified"
    assert verdict.diversity == 0.5
    assert {r.provider for r in verdict.reviews} == {"ollama"}


@pytest.mark.parametrize("model", ["different-model", "local-model:other", None])
def test_wrong_observed_model_fails_closed(server, model):
    server["responses"] = [(200, reply(model=model))]
    judge = make_judge(server)
    judge.retries = 0
    assert Panel([judge]).review(ReviewRequest(task="Add", output="4")).responded == 0


def test_omitted_latest_tag_is_only_allowed_alias(server):
    server["responses"] = [(200, reply(model="local-model:latest"))]
    review = make_judge(server).review(ReviewRequest(task="Add", output="4"))
    assert review.vote == "approve"
    assert review.model == review.params["requested_model"] == "local-model"
    assert review.observed_model == "local-model:latest"


def test_endpoint_and_secrets_are_not_saved(server):
    server["responses"] = [(200, reply())]
    review = make_judge(server).review(ReviewRequest(task="Add", output="4"))
    assert "endpoint_hash" in review.params
    assert server["url"] not in review.model_dump_json()
    assert review.observed_model == "local-model"


def test_invalid_usage_cannot_expose_provider_data(server):
    server["responses"] = [(200, reply(prompt_eval_count="SECRET_MARKER"))]
    judge = make_judge(server)
    judge.retries = 0
    verdict = Panel([judge]).review(ReviewRequest(task="Add", output="4"))
    assert verdict.responded == 0
    assert "SECRET_MARKER" not in verdict.model_dump_json()
