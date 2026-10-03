"""Static checks of the Claude Code plugin: user-invoked skills, no pre-approved send, a deny hook."""

import argparse
import fnmatch
import json
import re
from pathlib import Path

import pytest

from agentjury import change_review

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "integrations" / "claude-code"
SKILLS = ("review", "status", "adjudicate")
ALLOWED_PREFIXES = ("Bash(agentjury change ", "PowerShell(agentjury change ", "Edit(./.agentjury/changes/drafts/")


def frontmatter(path: Path) -> tuple[dict, str]:
    """The small YAML subset these skills use: scalars and one-level lists."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    assert match, f"{path} has no frontmatter"
    data: dict = {}
    key = None
    for line in match.group(1).splitlines():
        if line.startswith("  - "):
            data[key].append(line[4:].strip())
        else:
            key, _, value = line.partition(":")
            value = value.strip().strip('"')
            data[key] = [] if value == "" else value
    return data, match.group(2)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_and_marketplace_agree():
    manifest = load(PLUGIN / ".claude-plugin" / "plugin.json")
    marketplace = load(REPO / ".claude-plugin" / "marketplace.json")
    [entry] = marketplace["plugins"]
    assert manifest["name"] == entry["name"] == marketplace["name"] == "agentjury"
    assert entry["source"] == "./integrations/claude-code" and ".." not in entry["source"]
    assert (REPO / entry["source"]).resolve() == PLUGIN.resolve()
    assert marketplace["owner"]["name"] and manifest["version"]
    assert [p.name for p in (PLUGIN / ".claude-plugin").iterdir()] == ["plugin.json"]


@pytest.mark.parametrize("name", SKILLS)
def test_skills_are_user_invoked_and_never_pre_approve_sending(name):
    data, body = frontmatter(PLUGIN / "skills" / name / "SKILL.md")
    assert data["name"] == name
    assert data["disable-model-invocation"] == "true"
    assert data["description"]
    for tool in data["allowed-tools"]:
        assert tool.startswith(ALLOWED_PREFIXES), tool
        assert "send" not in tool and "adjudicate" not in tool and "*" in tool
    assert "untrusted" in body


def test_review_skill_injects_only_a_pre_approved_read_only_command():
    data, body = frontmatter(PLUGIN / "skills" / "review" / "SKILL.md")
    injected = re.findall(r"^!`([^`]*)`", body, re.MULTILINE)
    assert injected == ["agentjury change candidates"]
    assert "Bash(agentjury change candidates *)" in data["allowed-tools"]
    assert "Do not run it" in body and "a hook blocks it" in body
    assert "Never grade findings yourself" in body
    assert "not a calibrated probability" in body


def test_review_skill_prepare_command_uses_real_flags():
    _, body = frontmatter(PLUGIN / "skills" / "review" / "SKILL.md")
    [command] = re.findall(r"`(agentjury change prepare [^`]*)`", body)
    parser = argparse.ArgumentParser()
    change_review.add_parser(parser.add_subparsers())
    flags = sorted(set(re.findall(r"--[a-z-]+", command)))
    assert flags == ["--agent", "--framework", "--path", "--producer-provider", "--task-file", "--test-log"]
    tokens = ["change", "prepare"]
    for flag in flags:
        tokens += [flag, "value"]
    args = parser.parse_args(tokens)  # an unknown flag would exit here
    assert args.func is change_review.cmd_prepare and args.path == ["value"]


def hook_entries():
    config = load(PLUGIN / "hooks" / "hooks.json")
    assert set(config) == {"hooks"} and set(config["hooks"]) == {"PreToolUse"}
    return config["hooks"]["PreToolUse"]


def test_hook_denies_claude_initiated_sends_for_bash_and_powershell():
    entries = {entry["matcher"]: entry["hooks"] for entry in hook_entries()}
    assert set(entries) == {"Bash", "PowerShell"}
    for tool, hooks in entries.items():
        assert hooks
        for hook in hooks:
            assert hook["type"] == "command" and hook["if"].startswith(f"{tool}(") and "change send" in hook["if"]
            payload = re.fullmatch(r"echo '([^']*)'", hook["command"]).group(1)
            decision = json.loads(payload)["hookSpecificOutput"]
            assert decision["hookEventName"] == "PreToolUse"
            assert decision["permissionDecision"] == "deny"
            assert "only the user may send" in decision["permissionDecisionReason"]
            assert hook["timeout"] <= 30


@pytest.mark.parametrize("command, blocked", [
    ("agentjury change send 0123456789ab --confirm 0123456789abcdef", True),
    ("/home/u/.local/bin/agentjury change send 0123456789ab --confirm x", True),
    ("cd repo && agentjury change send 0123456789ab --confirm x", True),
    ("uvx agentjury change send 0123456789ab --confirm x", True),
    ("python -m agentjury.cli change send 0123456789ab --confirm x", True),
    ("agentjury change prepare --task-file t.md", False),
    ("agentjury change status", False),
    ("agentjury change candidates", False),
    ("agentjury review task.md output.md", False),
])
def test_hook_patterns_cover_common_send_forms(command, blocked):
    patterns = [hook["if"][len("Bash("):-1] for entry in hook_entries() if entry["matcher"] == "Bash"
                for hook in entry["hooks"]]
    assert any(fnmatch.fnmatchcase(command, pattern) for pattern in patterns) is blocked


def test_readme_and_packaging_reference_the_plugin():
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "/plugin marketplace add madad-rashid/AgentJury" in readme
    assert "/plugin install agentjury@agentjury" in readme
    assert "agentjury change send <id> --confirm <code>" in readme
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include integrations/claude-code *.md *.json" in manifest
    assert "include .claude-plugin/marketplace.json" in manifest
