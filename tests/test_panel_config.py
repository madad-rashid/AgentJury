"""CLI panel syntax selects explicit models without changing old panels."""

import pytest

from agentjury.judges import FakeJudge
from agentjury import panel_config
from agentjury.panel_config import build_panel


@pytest.fixture
def fake_factories(monkeypatch):
    seen = []

    for provider in ("openai", "anthropic", "openrouter", "ollama", "compatible"):
        def make(role, model=None, provider=provider):
            seen.append((role, provider, model))
            return FakeJudge(role, provider=provider)
        monkeypatch.setattr(panel_config, f"{provider}_judge", make)
    return seen


def test_old_panel_entries_keep_default_models(fake_factories):
    panel = build_panel("accuracy:openai,critic:anthropic")
    assert fake_factories == [
        ("accuracy", "openai", None),
        ("critic", "anthropic", None),
    ]
    assert len(panel.judges) == 2


def test_model_colon_is_preserved(fake_factories):
    panel = build_panel("accuracy:ollama:qwen3:8b", quorum=1)
    assert fake_factories == [("accuracy", "ollama", "qwen3:8b")]
    assert panel.quorum == 1


def test_explicit_direct_and_router_models(fake_factories):
    build_panel("accuracy:openai:gpt-example,critic:openrouter:anthropic/claude-sonnet-4")
    assert fake_factories == [
        ("accuracy", "openai", "gpt-example"),
        ("critic", "openrouter", "anthropic/claude-sonnet-4"),
    ]


@pytest.mark.parametrize("spec", [
    "accuracy:ollama",
    "accuracy:openrouter:",
    "accuracy:compatible",
    "accuracy:unknown:x",
    "accuracy",
    ",",
    "accuracy:openai,",
    "unknown:openai",
])
def test_invalid_panel_has_clear_error(spec, fake_factories):
    with pytest.raises(ValueError, match="[Pp]anel|provider|model|role"):
        build_panel(spec)


def test_cli_uses_shared_parser(monkeypatch):
    from agentjury import cli

    sentinel = object()
    seen = []

    def shared(spec, quorum=None):
        seen.append((spec, quorum))
        return sentinel

    monkeypatch.setattr(panel_config, "build_panel", shared)
    assert cli.build_panel("accuracy:ollama:qwen3:8b", quorum=1) is sentinel
    assert seen == [("accuracy:ollama:qwen3:8b", 1)]


def test_cli_reports_panel_error_without_traceback(monkeypatch):
    from agentjury import cli

    def shared(spec, quorum=None):
        raise ValueError("panel needs a model")

    monkeypatch.setattr(panel_config, "build_panel", shared)
    with pytest.raises(SystemExit, match="panel needs a model"):
        cli.build_panel("accuracy:ollama")
