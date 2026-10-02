"""
Judge backed by an Anthropic model.

Requires ANTHROPIC_API_KEY in the environment.

Workspace: if the key spans multiple workspaces, Anthropic requires an
`anthropic-workspace-id` header; set ANTHROPIC_WORKSPACE_ID and it is sent.

Thinking: Claude Sonnet 5 and later reason before answering by default, and
that reasoning counts against max_tokens. We give the model 4096 tokens and
default effort to "medium", which is plenty for a short JSON review.
  ANTHROPIC_EFFORT     low | medium | high   (default medium)
  ANTHROPIC_THINKING   adaptive | disabled   (default adaptive; Fable/Mythos reject disabled)
"""

from __future__ import annotations

import os

from .base import Completion, Judge
from .compatible import _response_id, _sanitized_error, _token_count
from .response_validation import direct_model_matches


class AnthropicJudge(Judge):
    provider = "anthropic"

    def __init__(self, role: str, model: str = "claude-sonnet-5", max_tokens: int = 4096,
                 effort: str | None = None, thinking: str | None = None, timeout: float = 90.0):
        super().__init__(role, model, timeout=timeout)
        try:
            from anthropic import Anthropic, DefaultHttpxClient
        except ImportError as exc:  # optional dependency
            raise ImportError(
                'The anthropic package is not installed. Run: pip install "agentjury[anthropic]"'
            ) from exc

        headers = {}
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        if workspace_id:
            headers["anthropic-workspace-id"] = workspace_id

        # max_retries=0: AgentJury owns the retry policy, not the SDK.
        self._client = Anthropic(default_headers=headers, timeout=timeout, max_retries=0,
                                http_client=DefaultHttpxClient(timeout=timeout, follow_redirects=False))
        self.max_tokens = max_tokens
        self.effort = effort or os.environ.get("ANTHROPIC_EFFORT", "medium")
        self.thinking = thinking or os.environ.get("ANTHROPIC_THINKING", "adaptive")
        self.params = {"max_tokens": max_tokens, "effort": self.effort, "thinking": self.thinking}

    def complete(self, system: str, user: str) -> Completion:
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
        )
        if self.thinking == "disabled":
            kwargs["thinking"] = {"type": "disabled"}

        try:
            response = self._client.messages.create(**kwargs)
            observed = getattr(response, "model", None)
            if (not direct_model_matches(self.model, observed, compact_date=True)
                    or getattr(response, "stop_reason", None) != "end_turn"):
                raise ValueError("model mismatch or incomplete completion")
            text = "".join(block.text for block in response.content if block.type == "text")
            if not text.strip():
                raise ValueError("empty completion")
            usage = getattr(response, "usage", None)
            return Completion(text=text, observed_model=observed,
                tokens_in=_token_count(getattr(usage, "input_tokens", None)),
                tokens_out=_token_count(getattr(usage, "output_tokens", None)),
                response_id=_response_id(getattr(response, "id", None)))
        except Exception as exc:  # noqa: BLE001 - SDK errors can include private bodies
            raise _sanitized_error("anthropic", self.model, exc) from None
