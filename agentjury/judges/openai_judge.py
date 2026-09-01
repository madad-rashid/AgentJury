"""Judge backed by an OpenAI model. Requires OPENAI_API_KEY in the environment."""

from __future__ import annotations

from .base import Completion, Judge


class OpenAIJudge(Judge):
    provider = "openai"

    def __init__(self, role: str, model: str = "gpt-5.6", timeout: float = 60.0):
        super().__init__(role, model, timeout=timeout)
        try:
            from openai import OpenAI
        except ImportError as exc:  # optional dependency
            raise ImportError(
                f"The openai package is not installed. Run: pip install \"agentjury[openai]\""
            ) from exc

        # max_retries=0: AgentJury owns the retry policy, not the SDK.
        self._client = OpenAI(timeout=timeout, max_retries=0)

    def complete(self, system: str, user: str) -> Completion:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
            response_id=getattr(response, "id", None),
        )
