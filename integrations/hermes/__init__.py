"""AgentJury plugin for Hermes: registration."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("agentjury.hermes")


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # provided by Hermes
        return Path(plugin_data_dir("agentjury"))
    except Exception:  # noqa: BLE001 - running outside Hermes (tests)
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "plugin-data" / "agentjury"


def register(ctx):
    try:
        import agentjury  # noqa: F401
    except ImportError:
        log.error("agentjury plugin: the agentjury package is not installed in Hermes's Python. "
                  "Run: pip install git+https://github.com/madad-rashid/AgentJury")
        return

    from .jury import Jury, Settings

    settings = Settings.from_ctx(ctx)
    missing = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if missing:
        log.warning("agentjury plugin: %s not set; judges using those providers will fail", ", ".join(missing))

    jury = Jury(settings, _data_dir())

    ctx.register_hook("post_tool_call", jury.on_tool_call)
    ctx.register_hook("post_llm_call", jury.on_turn_end)
    ctx.register_hook("pre_llm_call", jury.on_turn_start)
    ctx.register_command("jury", handler=jury.status,
                         description="Show the latest AgentJury verdict, or /jury <request_id>")
    log.info("agentjury plugin ready: panel=%s data=%s", settings.panel, jury.data_dir)
    return jury
