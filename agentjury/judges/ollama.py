"""Judge using Ollama's native local chat API. No API key or SDK required."""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from .base import Completion, Judge


class OllamaJudge(Judge):
    # Model names do not create extra provider diversity within a local server.
    provider = "ollama"

    def __init__(
        self, role: str, model: str | None = None, timeout: float = 120.0,
        base_url: str | None = None,
    ):
        model = model or os.environ.get("AGENTJURY_OLLAMA_MODEL")
        if not model or not model.strip():
            raise ValueError(
                "Set AGENTJURY_OLLAMA_MODEL to an installed Ollama model "
                "(see ollama list), or pass model= to OllamaJudge."
            )
        super().__init__(role, model, timeout=timeout)
        self.base_url = (base_url or os.environ.get("AGENTJURY_OLLAMA_URL")
                         or "http://localhost:11434").rstrip("/")
        self.params = {"base_url": self.base_url, "format": "json"}

    def complete(self, system: str, user: str) -> Completion:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        request = Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Shared Judge handles retries and opinion repair; no hidden SDK retries.
        with urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError("Ollama returned an error or invalid chat response.")
        message = data.get("message")
        if (data.get("done") is not True or not isinstance(message, dict)
                or not isinstance(message.get("content"), str)):
            raise ValueError("Ollama returned an incomplete or invalid chat message.")
        return Completion(
            text=message["content"],
            tokens_in=data.get("prompt_eval_count"),
            tokens_out=data.get("eval_count"),
        )
