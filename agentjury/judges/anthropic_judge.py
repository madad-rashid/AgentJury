"""
Judge backed by an Anthropic model.

Requires ANTHROPIC_API_KEY in the environment. If the key is a personal or
service-account key that spans multiple workspaces, Anthropic also requires an
`anthropic-workspace-id` header; set ANTHROPIC_WORKSPACE_ID and it is sent
automatically. Keys created for a single workspace do not need it.
"""

from __future__ import annotations

import os

from .base import Judge


class AnthropicJudge(Judge):
    provider = "anthropic"

    def __init__(self, role: str, model: str = "claude-sonnet-5"):
        super().__init__(role, model)
        from anthropic import Anthropic

        headers = {}
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        if workspace_id:
            headers["anthropic-workspace-id"] = workspace_id

        self._client = Anthropic(default_headers=headers)

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
