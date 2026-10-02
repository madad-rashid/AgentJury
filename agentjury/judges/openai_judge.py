"""Judge backed by an OpenAI model. Requires OPENAI_API_KEY in the environment."""

from __future__ import annotations

from .base import Completion, Judge
from .compatible import _response_id, _sanitized_error, _token_count
from .response_validation import direct_model_matches


class OpenAIJudge(Judge):
    provider = "openai"

    def __init__(self, role: str, model: str = "gpt-5.6", timeout: float = 60.0):
        super().__init__(role, model, timeout=timeout)
        try:
            from openai import DefaultHttpxClient, OpenAI
        except ImportError as exc:  # optional dependency
            raise ImportError(
                f"The openai package is not installed. Run: pip install \"agentjury[openai]\""
            ) from exc

        # max_retries=0: AgentJury owns the retry policy, not the SDK.
        self._client = OpenAI(timeout=timeout, max_retries=0,
                              http_client=DefaultHttpxClient(timeout=timeout, follow_redirects=False))

    def complete(self, system: str, user: str) -> Completion:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            observed = getattr(response, "model", None)
            if getattr(response, "error", None) or not direct_model_matches(self.model, observed):
                raise ValueError("model mismatch or response error")
            choices = response.choices
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("invalid choices")
            choice = choices[0]
            text = choice.message.content
            if (getattr(choice, "finish_reason", None) != "stop" or getattr(choice, "error", None)
                    or not isinstance(text, str) or not text.strip()):
                raise ValueError("incomplete completion")
            usage = getattr(response, "usage", None)
            return Completion(text=text, observed_model=observed,
                tokens_in=_token_count(getattr(usage, "prompt_tokens", None)),
                tokens_out=_token_count(getattr(usage, "completion_tokens", None)),
                response_id=_response_id(getattr(response, "id", None)))
        except Exception as exc:  # noqa: BLE001 - SDK errors can include private bodies
            raise _sanitized_error("openai", self.model, exc) from None
