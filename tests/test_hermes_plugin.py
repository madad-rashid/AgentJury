"""The Hermes plugin, exercised against a fake Hermes ctx. No API keys."""

import importlib.util
import sys
from pathlib import Path

import pytest

from agentjury import Panel
from agentjury.judges import FakeJudge

ROOT = Path(__file__).resolve().parent.parent / "integrations" / "hermes"


def load_plugin():
    """Import integrations/hermes as a package without installing it."""
    spec = importlib.util.spec_from_file_location("hermes_agentjury", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_agentjury"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeCtx:
    def __init__(self, config=None):
        self.config = config or {}
        self.hooks = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_command(self, name, handler, description=""):
        self.commands[name] = handler


def fake_panel(vote="approve", score=8, findings=None):
    def factory(settings):
        return Panel([
            FakeJudge("accuracy", provider="openai", vote=vote, score=score, findings=findings),
            FakeJudge("critic", provider="anthropic", vote=vote, score=score, findings=findings),
        ])
    return factory


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    mod = load_plugin()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return mod


def make_jury(plugin, tmp_path, **cfg):
    from hermes_agentjury.jury import Jury, Settings
    ctx = FakeCtx(cfg)
    settings = Settings.from_ctx(ctx)
    return Jury(settings, tmp_path / "data", panel_factory=cfg.pop("_factory", fake_panel())), ctx


def test_register_wires_hooks_and_command(plugin, tmp_path):
    ctx = FakeCtx()
    jury = plugin.register(ctx)
    assert set(ctx.hooks) == {"post_tool_call", "post_llm_call", "pre_llm_call"}
    assert "jury" in ctx.commands
    assert jury.data_dir == tmp_path / "plugin-data" / "agentjury"


def test_short_responses_are_skipped(plugin, tmp_path):
    jury, _ = make_jury(plugin, tmp_path, min_chars=100)
    assert jury.on_turn_end("s1", "hi", "hello!") is None


def test_turn_is_reviewed_and_saved(plugin, tmp_path):
    jury, _ = make_jury(plugin, tmp_path, min_chars=10, task_type="research", domain="credit")
    fut = jury.on_turn_end("s1", "Summarise private credit.", "Private credit grew because...", model="claude-sonnet-5")
    verdict = fut.result(timeout=10)
    assert verdict.status == "verified"
    assert verdict.task_type == "research" and verdict.domain == "credit"
    assert verdict.producer.framework == "hermes" and verdict.producer.provider == "anthropic"
    assert (jury.verdict_dir / f"{verdict.request_id}.json").is_file()


def test_written_markdown_gets_frontmatter_and_sidecar(plugin, tmp_path):
    note = tmp_path / "vault" / "Pilot.md"
    note.parent.mkdir()
    note.write_text("---\ntitle: Pilot\ntags: [madad]\n---\n# Pilot\n\nBody.\n", encoding="utf-8")

    jury, _ = make_jury(plugin, tmp_path, min_chars=10)
    jury.on_tool_call("write_file", {"path": str(note), "content": "..."}, task_id="s1")
    jury.on_turn_end("s1", "Write the pilot note.", "I wrote the pilot note with three sections...")
    jury.wait(10)

    text = note.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: Pilot\ntags: [madad]\nagentjury_status: verified\n")
    assert 'agentjury_votes: "▲2 ▼0"' in text
    assert text.endswith("# Pilot\n\nBody.\n")
    assert (tmp_path / "vault" / "Pilot.md.agentjury.json").is_file()

    # second review replaces, not duplicates, the keys
    jury.on_tool_call("write_file", {"path": str(note)}, task_id="s1")
    jury.on_turn_end("s1", "Revise it.", "Revised the pilot note thoroughly and expanded it.")
    jury.wait(10)
    assert note.read_text(encoding="utf-8").count("agentjury_status") == 1


def test_markdown_without_frontmatter_gets_one(plugin, tmp_path):
    note = tmp_path / "plain.md"
    note.write_text("# Plain\n", encoding="utf-8")
    jury, _ = make_jury(plugin, tmp_path, min_chars=10)
    jury.on_tool_call("patch", {"file_path": str(note)}, task_id="s1")
    jury.on_turn_end("s1", "t", "a long enough response here")
    jury.wait(10)
    assert note.read_text(encoding="utf-8").startswith("---\nagentjury_status: verified\n")


def test_written_file_becomes_artifact(plugin, tmp_path):
    seen = {}

    class Spy(FakeJudge):
        def complete(self, system, user):
            seen["user"] = user
            return super().complete(system, user)

    f = tmp_path / "out.md"
    f.write_text("ARTIFACT BODY", encoding="utf-8")
    jury, _ = make_jury(plugin, tmp_path, min_chars=10,
                        _factory=lambda s: Panel([Spy("accuracy", provider="openai"), Spy("critic", provider="anthropic")]))
    jury.on_tool_call("write_file", {"path": str(f)}, task_id="s1")
    jury.on_turn_end("s1", "t", "a long enough response here")
    jury.wait(10)
    assert "ARTIFACT out.md" in seen["user"] and "ARTIFACT BODY" in seen["user"]


def test_feedback_injected_once_when_not_verified(plugin, tmp_path):
    jury, _ = make_jury(plugin, tmp_path, min_chars=10,
                        _factory=fake_panel(vote="revise", score=5, findings=[{"text": "No source", "severity": "major"}]))
    jury.on_turn_end("s1", "t", "a long enough response here")
    jury.wait(10)
    inj = jury.on_turn_start("s1")
    assert inj and "No source" in inj["context"] and "needs_revision" in inj["context"]
    assert jury.on_turn_start("s1") is None  # consumed
    assert jury.on_turn_start("other") is None


def test_no_feedback_when_verified_or_disabled(plugin, tmp_path):
    jury, _ = make_jury(plugin, tmp_path, min_chars=10)
    jury.on_turn_end("s1", "t", "a long enough response here")
    jury.wait(10)
    assert jury.on_turn_start("s1") is None

    jury2, _ = make_jury(plugin, tmp_path, min_chars=10, feedback=False,
                         _factory=fake_panel(vote="revise", score=4))
    jury2.on_turn_end("s2", "t", "a long enough response here")
    jury2.wait(10)
    assert jury2.on_turn_start("s2") is None


def test_status_command(plugin, tmp_path):
    jury, _ = make_jury(plugin, tmp_path, min_chars=10)
    assert "no verdicts yet" in jury.status()
    fut = jury.on_turn_end("s1", "t", "a long enough response here")
    v = fut.result(10)
    out = jury.status()
    assert "▲2 ▼0" in out and "accuracy/openai" in out
    assert "▲2 ▼0" in jury.status(v.request_id)
    assert "No verdict" in jury.status("nope")


def test_infer_provider(plugin):
    from hermes_agentjury.jury import infer_provider
    assert infer_provider("gpt-5.6") == "openai"
    assert infer_provider("claude-sonnet-5") == "anthropic"
    assert infer_provider("gemini-3.7-flash") == "google"
    assert infer_provider("llama-4") is None and infer_provider(None) is None
