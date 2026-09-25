"""Shared panel syntax for the CLI and framework integrations."""

from __future__ import annotations

from .judges import (
    ROLES,
    anthropic_judge,
    compatible_judge,
    ollama_judge,
    openai_judge,
    openrouter_judge,
)
from .panel import Panel


def build_panel(spec: str, quorum: int | None = None) -> Panel:
    """Parse comma-separated ``role:provider[:model]`` entries."""
    factories = {
        "openai": openai_judge,
        "anthropic": anthropic_judge,
        "openrouter": openrouter_judge,
        "ollama": ollama_judge,
        "compatible": compatible_judge,
    }
    judges = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        fields = [part.strip() for part in item.split(":", 2)]
        if len(fields) not in (2, 3) or not all(fields):
            raise ValueError(f"Bad panel entry {item!r}. Use role:provider[:model].")
        role, provider = fields[:2]
        model = fields[2] if len(fields) == 3 else None
        if role not in ROLES:
            raise ValueError(f"Unknown role {role!r}. Known roles: {', '.join(sorted(ROLES))}")
        if provider not in factories:
            raise ValueError(f"Unknown provider {provider!r}. Known providers: {', '.join(factories)}")
        if model is None and provider in ("openrouter", "ollama", "compatible"):
            raise ValueError(f"The {provider} provider requires an explicit model in the panel entry.")
        judges.append(factories[provider](role, model))
    return Panel(judges, quorum=quorum)
