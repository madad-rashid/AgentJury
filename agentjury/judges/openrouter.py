"""OpenRouter transport with fixed model identity and no extra SDK dependency."""

from __future__ import annotations

import hashlib
import json
import os
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import Completion, Judge
from .compatible import _base_url, _response_id, _router_model, _router_model_matches, _sanitized_error, _token_count

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the bearer token or review material to another endpoint.
        return None


def _canonical_model(model: str) -> str:
    return _router_model(model)


class OpenRouterJudge(Judge):
    def __init__(self, role: str, model: str | None = None, timeout: float = 60.0):
        requested = model if model is not None else os.environ.get("AGENTJURY_OPENROUTER_MODEL", "")
        canonical = _canonical_model(requested)
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("Set OPENROUTER_API_KEY to use OpenRouter judges.")
        # Authors are a proxy for diversity; a gateway host adds no new author.
        self.provider = canonical.split("/", 1)[0].lower()
        super().__init__(role, canonical, timeout=timeout)
        self._requested_model = requested
        self._api_key = key
        self._api_url = _base_url(API_URL)
        self._opener = build_opener(_NoRedirect())
        self.params = {"route": "openrouter", "transport": "openrouter",
                       "endpoint_hash": hashlib.sha256(self._api_url.encode()).hexdigest()[:12],
                       "requested_model": requested}

    @property
    def name(self) -> str:
        return f"{self.role}/openrouter/{self._requested_model}"

    def complete(self, system: str, user: str) -> Completion:
        try:
            payload = {"model": self._requested_model,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                       "stream": False}
            request = Request(self._api_url, data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
                              method="POST")
            # Shared Judge owns provider retries, JSON repair, and review parsing.
            with self._opener.open(request, timeout=self.timeout) as response:
                data = json.load(response)
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("invalid response")
            observed = data.get("model")
            if not _router_model_matches(self._requested_model, observed):
                raise ValueError("model mismatch")
            choices = data.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError("invalid chat completion")
            choice = choices[0]
            message = choice.get("message")
            if (choice.get("error") or choice.get("finish_reason") != "stop"
                    or choice.get("native_finish_reason", "stop") not in ("stop", "end_turn", "STOP")
                    or not isinstance(message, dict) or not isinstance(message.get("content"), str)
                    or not message["content"].strip()):
                raise ValueError("incomplete chat message")
            usage = data.get("usage")
            if usage is None:
                usage = {}
            if not isinstance(usage, dict):
                raise ValueError("invalid usage")
            return Completion(text=message["content"], observed_model=observed,
                              tokens_in=_token_count(usage.get("prompt_tokens")),
                              tokens_out=_token_count(usage.get("completion_tokens")),
                              response_id=_response_id(data.get("id")))
        except Exception as exc:  # noqa: BLE001 - provider errors may echo secrets
            raise _sanitized_error("openrouter", self._requested_model, exc) from None
