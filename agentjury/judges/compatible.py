"""Chat Completions judge for OpenRouter, Ollama, and compatible endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import urlsplit, urlunsplit

from .base import Completion, Judge, prompt_hash

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
    scheme = parts.scheme.lower()
    hostname = parts.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = parts.port
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        host += f":{port}"
    return urlunsplit((scheme, host, parts.path.rstrip("/"), "", ""))


def _same_base_url(left: str, right: str) -> bool:
    try:
        return _base_url(left) == _base_url(right)
    except ValueError:
        return False


def _ollama_root(value: str) -> str:
    url = _base_url(value)
    return url[:-3] if url.endswith("/v1") else url


def _ollama_url() -> str:
    return _ollama_root(os.environ.get("AGENTJURY_OLLAMA_URL")
                        or os.environ.get("AGENTJURY_OLLAMA_BASE_URL") or OLLAMA_URL)


def _ollama_model(model: str) -> str:
    return model[:-7] if model.endswith(":latest") else model


def _ollama_model_matches(requested: str, observed: object) -> bool:
    return isinstance(observed, str) and _ollama_model(requested) == _ollama_model(observed)


def _ollama_config_id(judge: Judge) -> str:
    """Normalize aliases only for identity, retaining literal request telemetry."""
    params = {"timeout": judge.timeout, **judge.params}
    if "requested_model" in params:
        params["requested_model"] = _ollama_model(params["requested_model"])
    encoded = json.dumps(params, sort_keys=True, default=str)
    return prompt_hash(f"{judge.provider}|{_ollama_model(judge.model)}|{judge.role}|{judge.prompt_hash}|{encoded}")


def _router_model(model: str) -> str:
    if not isinstance(model, str) or not _MODEL_SLUG.fullmatch(model) or model.split("/", 1)[0].lower() == "openrouter":
        raise ValueError("OpenRouter model must use a stable vendor/model slug.")
    return model.split(":", 1)[0]


def _router_model_matches(requested: str, observed: object) -> bool:
    return isinstance(observed, str) and observed in (requested, _router_model(requested))


def _sanitized_error(route: str, model: str, exc: Exception) -> RuntimeError:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    detail = f", HTTP {status}" if isinstance(status, int) else ""
    return RuntimeError(f"{route} model {model}: {type(exc).__name__}{detail}")


def _token_count(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("invalid token usage")
    return value


def _response_id(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("invalid response identifier")
    return value


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
            "requested_model": model,
            "endpoint_hash": hashlib.sha256(url.encode("utf-8")).hexdigest()[:12],
        }
        try:
            from openai import DefaultHttpxClient, OpenAI
        except ImportError as exc:
            raise ImportError('The openai package is not installed. Run: pip install "agentjury[openai]"') from exc
        self._client = OpenAI(
            api_key=api_key or "agentjury-no-key",
            base_url=url,
            timeout=timeout,
            max_retries=0,
            http_client=DefaultHttpxClient(timeout=timeout, follow_redirects=False),
        )

    @property
    def name(self) -> str:
        return f"{self.role}/{self.route}/{self.model}"

    @property
    def config_id(self) -> str:
        return _ollama_config_id(self) if self.provider == "ollama" else super().config_id

    def complete(self, system: str, user: str) -> Completion:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            if getattr(response, "error", None):
                raise ValueError("error completion")
            observed = getattr(response, "model", None)
            if self.route == "openrouter":
                matches = _router_model_matches(self.model, observed)
            elif self.provider == "ollama":
                matches = _ollama_model_matches(self.model, observed)
            else:
                matches = observed is None or observed == self.model
            if not matches:
                raise ValueError("model mismatch")
            choices = response.choices
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("invalid choices")
            choice = choices[0]
            if getattr(choice, "error", None) or getattr(choice, "finish_reason", None) != "stop":
                raise ValueError("incomplete completion")
            if getattr(choice, "native_finish_reason", "stop") not in ("stop", "end_turn", "STOP"):
                raise ValueError("incomplete native completion")
            content = choice.message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty completion")
            usage = getattr(response, "usage", None)
            return Completion(
                text=content,
                observed_model=observed,
                tokens_in=_token_count(getattr(usage, "prompt_tokens", None)),
                tokens_out=_token_count(getattr(usage, "completion_tokens", None)),
                response_id=_response_id(getattr(response, "id", None)),
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors may echo secrets
            raise _sanitized_error(self.route, self.model, exc) from None


def openrouter_judge(role: str, model: str) -> CompatibleJudge:
    _router_model(model)
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
        base_url=_ollama_url() + "/v1",
        api_key=None, provider="ollama",
    )


def compatible_judge(role: str, model: str) -> CompatibleJudge:
    url = os.environ.get("AGENTJURY_COMPATIBLE_BASE_URL", "").strip()
    if not url:
        raise ValueError("Set AGENTJURY_COMPATIBLE_BASE_URL to use compatible judges.")
    try:
        same_ollama = _base_url(url) == _ollama_url() + "/v1"
    except ValueError:
        same_ollama = False
    provider = "ollama" if same_ollama else "compatible"
    return CompatibleJudge(
        role, model, route="compatible", base_url=url,
        api_key=os.environ.get("AGENTJURY_COMPATIBLE_API_KEY"), provider=provider,
    )
