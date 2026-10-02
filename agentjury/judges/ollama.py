"""Judge using Ollama's native local chat API. No API key or SDK required."""

from __future__ import annotations

import hashlib
import json
import os
from urllib.request import Request, build_opener

from .base import Completion, Judge
from .compatible import _ollama_config_id, _ollama_model_matches, _ollama_root, _ollama_url, _sanitized_error, _token_count
from .openrouter import _NoRedirect


class OllamaJudge(Judge):
    # Model names do not create extra provider diversity within a local server.
    provider = "ollama"

    def __init__(
        self, role: str, model: str | None = None, timeout: float = 120.0,
        base_url: str | None = None,
    ):
        model = model if model is not None else os.environ.get("AGENTJURY_OLLAMA_MODEL")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Set AGENTJURY_OLLAMA_MODEL to an installed Ollama model, or pass model= to OllamaJudge.")
        super().__init__(role, model, timeout=timeout)
        self.base_url = _ollama_root(base_url) if base_url is not None else _ollama_url()
        self._opener = build_opener(_NoRedirect())
        self.params = {"route": "ollama", "transport": "ollama", "format": "json",
                       "requested_model": model,
                       "endpoint_hash": hashlib.sha256(self.base_url.encode()).hexdigest()[:12]}

    @property
    def name(self) -> str:
        return f"{self.role}/ollama/{self.model}"

    @property
    def config_id(self) -> str:
        return _ollama_config_id(self)

    def complete(self, system: str, user: str) -> Completion:
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False,
                "format": "json",
            }
            request = Request(self.base_url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"}, method="POST")
            # Shared Judge handles retries and opinion repair; no hidden SDK retries.
            with self._opener.open(request, timeout=self.timeout) as response:
                data = json.load(response)
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("invalid chat response")
            observed = data.get("model")
            if not _ollama_model_matches(self.model, observed):
                raise ValueError("model mismatch")
            message = data.get("message")
            if (data.get("done") is not True or data.get("done_reason", "stop") != "stop"
                    or not isinstance(message, dict) or not isinstance(message.get("content"), str)
                    or not message["content"].strip()):
                raise ValueError("incomplete chat message")
            return Completion(text=message["content"], observed_model=observed,
                              tokens_in=_token_count(data.get("prompt_eval_count")),
                              tokens_out=_token_count(data.get("eval_count")))
        except Exception as exc:  # noqa: BLE001 - transport errors may echo endpoints
            raise _sanitized_error("ollama", self.model, exc) from None
