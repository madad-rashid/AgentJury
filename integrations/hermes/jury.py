"""
AgentJury for Hermes: the logic behind the hooks.

Turn lifecycle:
  post_tool_call   remember every file Hermes wrote this turn
  post_llm_call    build a ReviewRequest from (user_message, assistant_response, files),
                   run the panel in a background thread, save the verdict, annotate files
  pre_llm_call     if the last verdict for this session was not verified, hand the
                   findings to the model once so it can address them

Nothing here touches AgentJury's core. It only builds requests and consumes verdicts.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agentjury import Artifact, Panel, Producer, ReviewRequest, Verdict
from agentjury.judges import ROLES, anthropic_judge, load_roles, openai_judge

log = logging.getLogger("agentjury.hermes")

WRITE_TOOLS = {"write_file", "patch", "file_edit", "edit_file", "create_file", "append_file"}
PATH_KEYS = ("path", "file_path", "filename", "file", "target")
MAX_ARTIFACTS = 5
MAX_ARTIFACT_CHARS = 20_000
PROVIDERS = {"openai": openai_judge, "anthropic": anthropic_judge}


@dataclass
class Settings:
    panel: str = "accuracy:openai,critic:anthropic,executive:openai"
    roles_file: str = ""
    context_file: str = ""
    quorum: int = 0
    min_chars: int = 400
    task_type: str = ""
    domain: str = ""
    frontmatter: bool = True
    sidecar: bool = True
    feedback: bool = True

    @classmethod
    def from_ctx(cls, ctx) -> "Settings":
        s = cls()
        for name in s.__dataclass_fields__:
            try:
                val = ctx.get_config(name, default=getattr(s, name))
            except Exception:  # noqa: BLE001 - never let config reading kill the plugin
                val = getattr(s, name)
            setattr(s, name, val)
        return s


def infer_provider(model: str | None) -> str | None:
    if not model:
        return None
    m = model.lower()
    if "gpt" in m or m.startswith("o") and m[1:2].isdigit():
        return "openai"
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "google"
    return None


def build_panel(settings: Settings) -> Panel:
    if settings.roles_file:
        load_roles(settings.roles_file)
    judges = []
    for item in settings.panel.split(","):
        item = item.strip()
        if not item:
            continue
        role, provider = item.split(":")
        if role not in ROLES:
            raise ValueError(f"Unknown role {role!r}")
        judges.append(PROVIDERS[provider](role))
    return Panel(judges, quorum=settings.quorum or None)


def read_artifact(path: str) -> Artifact | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) > MAX_ARTIFACT_CHARS:
        text = text[:MAX_ARTIFACT_CHARS] + f"\n\n[... truncated, {len(text)} chars total]"
    return Artifact(name=p.name, content=text, media_type="text/markdown" if p.suffix == ".md" else "text/plain")


# ---------------------------------------------------------------------------
# Annotating files Hermes wrote
# ---------------------------------------------------------------------------

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_KEYS = ("agentjury_status", "agentjury_votes", "agentjury_score", "agentjury_confidence", "agentjury_id", "agentjury_at")


def frontmatter_lines(verdict: Verdict) -> list[str]:
    return [
        f"agentjury_status: {verdict.status}",
        f"agentjury_votes: \"▲{verdict.up} ▼{verdict.down}\"",
        f"agentjury_score: {verdict.score}",
        f"agentjury_confidence: {verdict.confidence}",
        f"agentjury_id: {verdict.request_id}",
        f"agentjury_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]


def write_frontmatter(path: Path, verdict: Verdict) -> bool:
    """Upsert agentjury_* keys into a markdown file's YAML frontmatter. Creates one if absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    new = frontmatter_lines(verdict)
    m = _FM.match(text)
    if m:
        kept = [ln for ln in m.group(1).splitlines() if not ln.startswith(_KEYS)]
        body = text[m.end():]
        out = "---\n" + "\n".join(kept + new) + "\n---\n" + body
    else:
        out = "---\n" + "\n".join(new) + "\n---\n" + text
    path.write_text(out, encoding="utf-8")
    return True


def write_sidecar(path: Path, verdict: Verdict) -> Path:
    side = path.with_suffix(path.suffix + ".agentjury.json")
    side.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return side


def render_verdict(verdict: Verdict, files: list[str] | None = None) -> str:
    lines = [verdict.render(), f"jury confidence index {verdict.confidence:.0%}"]
    for r in verdict.reviews:
        arrow = {"approve": "▲", "revise": "▼", "abstain": "–"}[r.vote]
        lines.append(f"{arrow} {r.score:.0f}  {r.judge}: {r.reason}")
        for f in r.findings:
            lines.append(f"      [{f.severity}] {f.text}")
    for e in verdict.errors:
        lines.append(f"!  {e}")
    if files:
        lines.append("files: " + ", ".join(files))
    return "\n".join(lines)


def feedback_text(verdict: Verdict) -> str:
    """What the model sees at the start of the next turn if the last verdict was not verified."""
    findings = [
        f"- [{f.severity}] ({r.judge}) {f.text}"
        for r in verdict.reviews for f in r.findings if f.severity != "minor"
    ] or [f"- ({r.judge}) {r.reason}" for r in verdict.reviews if r.vote == "revise"]
    return (
        f"AgentJury peer review of your previous response: {verdict.render()}.\n"
        f"Independent reviewers raised these points:\n" + "\n".join(findings[:8]) +
        "\nIf the user is continuing the same task, address these. Do not mention this note unless asked."
    )


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class TurnFiles:
    paths: list[str] = field(default_factory=list)


class Jury:
    def __init__(self, settings: Settings, data_dir: Path, panel_factory=build_panel):
        self.settings = settings
        self.data_dir = data_dir
        self.verdict_dir = data_dir / "verdicts"
        self.verdict_dir.mkdir(parents=True, exist_ok=True)
        self._panel_factory = panel_factory
        self._panel: Panel | None = None
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agentjury")
        self._lock = threading.Lock()
        self.files: dict[str, TurnFiles] = {}
        self.pending: dict[str, Future] = {}
        self.last: dict[str, Verdict] = {}
        self.last_files: dict[str, list[str]] = {}
        self.unread_feedback: set[str] = set()
        self.context = Path(settings.context_file).read_text(encoding="utf-8") if settings.context_file else None

    # -- hooks ---------------------------------------------------------------

    def on_tool_call(self, tool_name: str, args: dict, task_id: str, **_) -> None:
        if tool_name not in WRITE_TOOLS or not isinstance(args, dict):
            return
        for key in PATH_KEYS:
            p = args.get(key)
            if isinstance(p, str) and p:
                with self._lock:
                    tf = self.files.setdefault(task_id or "", TurnFiles())
                    if p not in tf.paths:
                        tf.paths.append(p)
                break

    RESPONSE_KEYS = ("assistant_response", "response", "assistant_message", "final_response", "reply", "content")
    MESSAGE_KEYS = ("user_message", "message", "prompt", "input")

    def on_turn_end(self, session_id: str | None = None, user_message: str | None = None,
                    assistant_response: str | None = None, model: str | None = None, **kw) -> Future | None:
        # Hermes builds vary in payload naming; accept the documented names and common alternatives.
        if not assistant_response:
            assistant_response = next((kw[k] for k in self.RESPONSE_KEYS if isinstance(kw.get(k), str) and kw[k]), None)
        if not user_message:
            user_message = next((kw[k] for k in self.MESSAGE_KEYS if isinstance(kw.get(k), str) and kw[k]), None)
        session_id = session_id or kw.get("task_id") or kw.get("session") or "default"

        if not assistant_response:
            log.warning("agentjury: post_llm_call had no response text; payload keys=%s", sorted(kw))
            return None
        log.info("agentjury: post_llm_call session=%s chars=%d model=%s", session_id, len(assistant_response), model)
        if len(assistant_response) < self.settings.min_chars:
            log.info("agentjury: skipped, %d chars < min_chars %d", len(assistant_response), self.settings.min_chars)
            return None
        with self._lock:
            paths = self.files.pop(session_id, TurnFiles()).paths
        artifacts = [a for a in (read_artifact(p) for p in paths[:MAX_ARTIFACTS]) if a]
        request = ReviewRequest(
            task=user_message or "(no user message captured)",
            output=assistant_response,
            context=self.context,
            task_type=self.settings.task_type or None,
            domain=self.settings.domain or None,
            artifacts=artifacts,
            producer=Producer(agent="hermes", framework="hermes", provider=infer_provider(model), model=model),
        )
        fut = self._pool.submit(self._review, session_id, request, paths)
        self.pending[session_id] = fut
        return fut

    def on_turn_start(self, session_id: str, **_) -> dict | None:
        if not self.settings.feedback or session_id not in self.unread_feedback:
            return None
        self.unread_feedback.discard(session_id)
        verdict = self.last.get(session_id)
        if verdict is None or verdict.status == "verified":
            return None
        return {"context": feedback_text(verdict)}

    # -- work ----------------------------------------------------------------

    def _review(self, session_id: str, request: ReviewRequest, paths: list[str]) -> Verdict:
        try:
            return self._review_inner(session_id, request, paths)
        except Exception:
            log.exception("agentjury: review failed for session %s", session_id)
            raise

    def _review_inner(self, session_id: str, request: ReviewRequest, paths: list[str]) -> Verdict:
        if self._panel is None:
            self._panel = self._panel_factory(self.settings)
        verdict = self._panel.review(request)
        (self.verdict_dir / f"{verdict.request_id}.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
        for p in paths:
            path = Path(p)
            if not path.is_file():
                continue
            try:
                if self.settings.sidecar:
                    write_sidecar(path, verdict)
                if self.settings.frontmatter and path.suffix.lower() == ".md":
                    write_frontmatter(path, verdict)
            except OSError as exc:
                log.warning("agentjury: could not annotate %s: %s", p, exc)
        self.last[session_id] = verdict
        self.last_files[session_id] = paths
        if verdict.status != "verified":
            self.unread_feedback.add(session_id)
        log.info("agentjury: %s  %s", verdict.render(), ", ".join(paths))
        return verdict

    # -- slash command -------------------------------------------------------

    def status(self, raw_args: str = "") -> str:
        arg = raw_args.strip()
        if arg:
            f = self.verdict_dir / f"{arg}.json"
            if f.is_file():
                return render_verdict(Verdict.model_validate_json(f.read_text(encoding="utf-8")))
            return f"No verdict {arg!r}. Saved verdicts are in {self.verdict_dir}"
        running = [s for s, fut in self.pending.items() if not fut.done()]
        if running and not self.last:
            return f"AgentJury: review in progress for {len(running)} session(s)..."
        if not self.last:
            return f"AgentJury: no verdicts yet. Panel: {self.settings.panel}"
        session = max(self.last, key=lambda s: self.last[s].created_at)
        head = "(review in progress for the latest turn)\n" if running else ""
        return head + render_verdict(self.last[session], self.last_files.get(session))

    def wait(self, timeout: float | None = None) -> None:
        for fut in list(self.pending.values()):
            fut.result(timeout=timeout)
