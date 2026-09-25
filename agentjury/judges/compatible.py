"""Chat Completions judge for OpenRouter, Ollama, and compatible endpoints."""

from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlsplit

from .base import Completion, Judge

OPENROUTER_URL = "https://openrouter.ai/api/v1"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
_MODEL_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[^\s/][^\s]*\Z")


def _base_url(value: str) -> str:
    """Validate a user-selected API base without exposing it in errors."""
    url = value.strip().rstrip("/")
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and parts.port != 0
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and not any(char.isspace() for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Endpoint URL must be an absolute HTTP(S) URL without credentials, query, or fragment.")
    return url


def _same_base_url(left: str, right: str) -> bool:
    try:
        return _base_url(left) == _base_url(right)
    except ValueError:
        return False


class CompatibleJudge(Judge):
    """One reviewer routed through an OpenAI-compatible chat endpoint."""

    def __init__(self, role: str, model: str, *, route: str, base_url: str,
                 api_key: str | None, provider: str, timeout: float = 60.0):
        if not model or not model.strip():
            raise ValueError(f"{route} requires an explicit model.")
        url = _base_url(base_url)
        super().__init__(role, model, timeout=timeout)
        self.route = route
        self.provider = provider
        self.params = {
            "route": route,
            "endpoint_hash": hashlib.sha256(url.encode("utf-8")).hexdigest()[:12],
        }
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError('The openai package is not installed. Run: pip install "agentjury[openai]"') from exc
        self._client = OpenAI(
            api_key=api_key or "agentjury-no-key",
            base_url=url,
            timeout=timeout,
            max_retries=0,
        )

    @property
    def name(self) -> str:
        return f"{self.role}/{self.route}/{self.model}"

    def complete(self, system: str, user: str) -> Completion:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty completion")
            usage = response.usage
            return Completion(
                text=content,
                tokens_in=getattr(usage, "prompt_tokens", None),
                tokens_out=getattr(usage, "completion_tokens", None),
                response_id=getattr(response, "id", None),
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors may echo secrets
            status = getattr(exc, "status_code", None)
            detail = f", HTTP {status}" if isinstance(status, int) else ""
            raise RuntimeError(
                f"{self.route} model {self.model}: {type(exc).__name__}{detail}"
            ) from None


def openrouter_judge(role: str, model: str) -> CompatibleJudge:
    if not _MODEL_SLUG.fullmatch(model):
        raise ValueError("OpenRouter model must use a stable vendor/model slug.")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("Set OPENROUTER_API_KEY to use OpenRouter judges.")
    vendor = model.split("/", 1)[0].lower()
    if vendor == "openrouter":
        raise ValueError("OpenRouter model must use a stable vendor/model slug.")
    return CompatibleJudge(
        role, model, route="openrouter", base_url=OPENROUTER_URL,
        api_key=key, provider=vendor,
    )


def ollama_judge(role: str, model: str) -> CompatibleJudge:
    return CompatibleJudge(
        role, model, route="ollama",
        base_url=os.environ.get("AGENTJURY_OLLAMA_BASE_URL") or OLLAMA_URL,
        api_key=None, provider="ollama",
    )


def compatible_judge(role: str, model: str) -> CompatibleJudge:
    url = os.environ.get("AGENTJURY_COMPATIBLE_BASE_URL", "").strip()
    if not url:
        raise ValueError("Set AGENTJURY_COMPATIBLE_BASE_URL to use compatible judges.")
    ollama_url = os.environ.get("AGENTJURY_OLLAMA_BASE_URL") or OLLAMA_URL
    provider = "ollama" if _same_base_url(url, ollama_url) else "compatible"
    return CompatibleJudge(
        role, model, route="compatible", base_url=url,
        api_key=os.environ.get("AGENTJURY_COMPATIBLE_API_KEY"), provider=provider,
    )
