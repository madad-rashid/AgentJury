"""OpenRouter transport with fixed model identity and no extra SDK dependency."""

from __future__ import annotations

import json
import os
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import Completion, Judge

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the bearer token to another endpoint.
        return None


def _canonical_model(model: str) -> str:
    if not isinstance(model, str) or not re.fullmatch(
        r"[a-z0-9-]+/[a-zA-Z0-9._-]+(?::[a-zA-Z0-9._-]+)*", model
    ) or model.startswith("openrouter/"):
        raise ValueError(
            "OpenRouter requires a fixed author/model slug from its model catalog. "
            "Automatic routers, latest aliases, and presets are not supported."
        )
    return model.split(":", 1)[0]


class OpenRouterJudge(Judge):
    def __init__(self, role: str, model: str | None = None, timeout: float = 60.0):
        requested = model if model is not None else os.environ.get("AGENTJURY_OPENROUTER_MODEL", "")
        canonical = _canonical_model(requested)
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ValueError("Set OPENROUTER_API_KEY to use OpenRouter judges.")
        # Count model authors, not the common gateway or inference host. This
        # also keeps direct OpenAI and routed OpenAI in the same provider group.
        self.provider = canonical.split("/", 1)[0]
        super().__init__(role, canonical, timeout=timeout)
        self._requested_model = requested
        self._api_key = key
        self._opener = build_opener(_NoRedirect())
        self.params = {"transport": "openrouter", "endpoint": API_URL,
                       "requested_model": requested}

    def complete(self, system: str, user: str) -> Completion:
        payload = {
            "model": self._requested_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
        }
        request = Request(
            self.params["endpoint"], data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        # Shared Judge owns provider retries, JSON repair, and review parsing.
        with self._opener.open(request, timeout=self.timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError("OpenRouter returned an error or invalid response.")
        if _canonical_model(data.get("model")) != self.model:
            raise ValueError("OpenRouter response model differs from the requested fixed model.")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("OpenRouter returned no valid chat completion.")
        choice = choices[0]
        message = choice.get("message")
        if (choice.get("error") or choice.get("finish_reason") != "stop"
                or not isinstance(message, dict) or not isinstance(message.get("content"), str)):
            raise ValueError("OpenRouter returned an incomplete or invalid chat message.")
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("OpenRouter returned invalid usage data.")
        return Completion(
            text=message["content"], tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"), response_id=data.get("id"),
        )
