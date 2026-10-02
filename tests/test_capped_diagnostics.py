"""Offline diagnostic regressions: synthetic bodies, no credentials or inference."""
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

SPEC = importlib.util.spec_from_file_location(
    "capped_diagnostics", Path(__file__).parents[1] / "experiments/openrouter/capped_transport.py"
)
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
MESSAGES = [{"role": "system", "content": "synthetic system"}, {"role": "user", "content": "synthetic task"}]


def body(**changes):
    value = {"id": "gen-synthetic-id", "model": "openai/gpt-6.1-sol", "provider": "OpenAI",
             "choices": [{"finish_reason": "stop", "native_finish_reason": "stop",
                          "message": {"content": "sensitive response must never be logged"}}],
             "usage": {"cost": 0.0002, "prompt_tokens": 100, "completion_tokens": 10}}
    value.update(changes)
    return value


class Offline:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def open(self, req, timeout):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return io.BytesIO(json.dumps(self.value).encode())


def run(tmp_path, value):
    ledger = h.Ledger(tmp_path / "journal.json")
    inner = Offline(value)
    transport = h.CappedTransport(inner, ledger, "synthetic", "openai/gpt-6.1-sol",
                                  MESSAGES, "repair", lambda a, b: a == b)
    req = Request("https://openrouter.ai/api/v1/chat/completions", method="POST",
                  data=json.dumps({"model": "openai/gpt-6.1-sol", "messages": MESSAGES, "stream": False}).encode(),
                  headers={"Authorization": "Bearer sk-or-v1-PRIVATE"})
    return ledger, inner, transport, req


@pytest.mark.parametrize("changes,stage,category", [
    ({"choices": []}, "completion", "missing_choice"),
    ({"choices": [{"finish_reason": "tool_calls"}]}, "completion", "unexpected_finish_reason"),
    ({"choices": [{"finish_reason": "length"}]}, "completion", "truncated_completion"),
    ({"choices": [{"finish_reason": "stop", "native_finish_reason": "max_tokens"}]}, "completion", "truncated_completion"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, "completion", "missing_content"),
    ({"model": "other/model"}, "model", "model_mismatch"),
    ({"provider": "Azure"}, "provider", "provider_mismatch"),
    ({"error": {"code": "unsupported_parameter", "message": "SECRET"}}, "provider_response", "unsupported_controls"),
    ({"usage": {"cost": 0.0002, "prompt_tokens": True, "completion_tokens": 1}}, "accounting", "invalid_accounting"),
    ({"usage": {"cost": "NaN", "prompt_tokens": 1, "completion_tokens": 1}}, "accounting", "invalid_accounting"),
])
def test_failure_records_stage_and_safe_category_without_retry(tmp_path, changes, stage, category):
    ledger, inner, transport, req = run(tmp_path, body(**changes))
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    diagnostic = ledger.calls[0]["diagnostic"]
    assert diagnostic["validation_stage"] == stage
    assert diagnostic["error_category"] == category
    assert ledger.halted and inner.calls == 1
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    assert inner.calls == 1


def test_truncation_preserves_metadata_before_rejection(tmp_path):
    ledger, _, transport, req = run(tmp_path, body(choices=[{"finish_reason": "length", "native_finish_reason": "max_tokens"}]))
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    d = ledger.calls[0]["diagnostic"]
    assert d["finish_reason"] == "length" and d["native_finish_reason"] == "max_tokens"
    assert d["observed_model"] == "openai/gpt-6.1-sol" and d["observed_provider"] == "OpenAI"
    assert d["generation_id"]["sha256"] and "value" not in d["generation_id"]
    assert ledger.calls[0]["reported_cost_usd"] == "0.0002"


@pytest.mark.parametrize("status", [400, 401, 402, 429, 500])
def test_http_failure_logs_status_without_body_headers_or_exception(tmp_path, status):
    error = HTTPError("https://secret.invalid/PRIVATE", status, "PRIVATE", {"Authorization": "PRIVATE"}, io.BytesIO(b"PRIVATE"))
    ledger, inner, transport, req = run(tmp_path, error)
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    d = ledger.calls[0]["diagnostic"]
    assert d["http_status"] == status and d["error_category"] == "http_failure"
    assert "PRIVATE" not in ledger.path.read_text() and inner.calls == 1


def test_success_journal_does_not_store_request_or_response_content(tmp_path):
    ledger, _, transport, req = run(tmp_path, body())
    with transport.open(req, 90) as response:
        assert json.load(response)["choices"][0]["message"]["content"]
    saved = ledger.path.read_text()
    assert "sensitive response" not in saved and "synthetic task" not in saved
    assert "sk-or-v1" not in saved and "gen-synthetic-id" not in saved
    assert ledger.calls[0]["diagnostic"]["validation_stage"] == "accepted"


def test_untrusted_metadata_cannot_leak_free_text_or_secrets(tmp_path):
    secret = "Bearer sk-or-v1-PRIVATE"
    ledger, _, transport, req = run(tmp_path, body(id=secret, model=secret, provider=secret,
        choices=[{"finish_reason": secret, "native_finish_reason": secret,
                  "error": {"message": secret}, "message": {"content": secret}}]))
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    assert "PRIVATE" not in ledger.path.read_text()
    assert ledger.calls[0]["diagnostic"]["observed_model"] == "unrecognized"


def test_known_cost_survives_malformed_token_metadata(tmp_path):
    ledger, _, transport, req = run(tmp_path, body(usage={"cost": 0.0002, "prompt_tokens": "SECRET", "completion_tokens": 10}))
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    assert ledger.calls[0]["reported_cost_usd"] == "0.0002"
    assert "SECRET" not in ledger.path.read_text()


@pytest.mark.parametrize("choices,category", [
    (None, "missing_choice"), ({}, "missing_choice"), ([{}, {}], "missing_choice"),
    ([None], "missing_choice"),
    ([{"finish_reason": "stop", "error": {"message": "PRIVATE"}}], "choice_error"),
    ([{"message": {"content": "PRIVATE"}}], "unexpected_finish_reason"),
    ([{"finish_reason": None}], "unexpected_finish_reason"),
    ([{"finish_reason": "stop", "native_finish_reason": None}], "unexpected_native_finish_reason"),
    ([{"finish_reason": "stop", "native_finish_reason": "PRIVATE"}], "unexpected_native_finish_reason"),
    ([{"finish_reason": "content_filter"}], "unexpected_finish_reason"),
    ([{"finish_reason": "stop", "message": []}], "missing_content"),
    ([{"finish_reason": "stop", "message": {"content": None}}], "missing_content"),
    ([{"finish_reason": "stop", "message": {"content": ["PRIVATE"]}}], "missing_content"),
    ([{"finish_reason": "stop", "message": {"content": "  "}}], "missing_content"),
])
def test_all_completion_shape_branches_remain_closed(tmp_path, choices, category):
    ledger, inner, transport, req = run(tmp_path, body(choices=choices))
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    assert ledger.halted == "incomplete_completion"
    assert ledger.calls[0]["diagnostic"]["error_category"] == category
    assert "PRIVATE" not in ledger.path.read_text()
    assert inner.calls == 1


@pytest.mark.parametrize("native", ["stop", "end_turn", "STOP", "absent"])
def test_native_valid_response_bytes_are_unchanged(tmp_path, native):
    value = body()
    if native == "absent":
        del value["choices"][0]["native_finish_reason"]
    else:
        value["choices"][0]["native_finish_reason"] = native
    _, inner, transport, req = run(tmp_path, value)
    assert transport.open(req, 90).read() == json.dumps(value).encode()
    assert inner.calls == 1


def test_failure_to_persist_reservation_prevents_dispatch(tmp_path, monkeypatch):
    ledger, inner, transport, req = run(tmp_path, body())
    def fail():
        raise OSError("PRIVATE")
    monkeypatch.setattr(ledger, "save", fail)
    with pytest.raises(OSError):
        transport.open(req, 90)
    assert inner.calls == 0


def test_nonjson_response_halts_without_logging_body(tmp_path):
    ledger, inner, transport, req = run(tmp_path, body())
    inner.open = lambda *a, **k: io.BytesIO(b"PRIVATE non-json")
    with pytest.raises(h.TestStopped):
        transport.open(req, 90)
    assert ledger.calls[0]["diagnostic"]["error_category"] == "malformed_response"
    assert "PRIVATE" not in ledger.path.read_text()


@pytest.mark.parametrize("field", ["id", "request_id"])
def test_surrogate_identifier_diagnostics_do_not_change_acceptance(tmp_path, field):
    value = body(**{field: "\ud800"})
    ledger, _, transport, req = run(tmp_path, value)
    assert transport.open(req, 90).read() == json.dumps(value).encode()
    assert ledger.calls[0]["reported_cost_usd"] == "0.0002"
    assert ledger.calls[0]["diagnostic"]["validation_stage"] == "accepted"
