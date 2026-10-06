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

import hashlib
import logging
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agentjury import Artifact, ArtifactCoverage, Panel, Producer, ReviewRequest, Verdict
from agentjury import panel_config
from agentjury.judges import load_roles
from agentjury.reviewer_guard import escape_controls

log = logging.getLogger("agentjury.hermes")

WRITE_TOOLS = {"write_file", "patch", "file_edit", "edit_file", "create_file", "append_file"}
PATH_KEYS = ("path", "file_path", "filename", "file", "target")
MAX_ARTIFACTS = 5
MAX_ARTIFACT_CHARS = 20_000


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
    return panel_config.build_panel(settings.panel, quorum=settings.quorum or None)


def read_artifact(path: str) -> Artifact | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        text = stripped_content(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None
    digest = content_digest(text)
    coverage = "full"
    if len(text) > MAX_ARTIFACT_CHARS:
        coverage = "partial"
        text = text[:MAX_ARTIFACT_CHARS] + f"\n\n[... truncated, {len(text)} chars total]"
    return Artifact(name=p.name, content=text, content_sha256=digest, coverage=coverage,
                    media_type="text/markdown" if p.suffix.lower() == ".md" else "text/plain")


# ---------------------------------------------------------------------------
# Annotating files Hermes wrote
# ---------------------------------------------------------------------------

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_KEYS = ("agentjury_status", "agentjury_votes", "agentjury_score", "agentjury_confidence",
         "agentjury_id", "agentjury_request_id", "agentjury_run_id", "agentjury_at",
         "agentjury_content_sha256")


def stripped_content(text: str) -> str:
    """Exclude machine certification from the next review and digest."""
    match = _FM.match(text)
    if not match:
        return text
    kept = [line for line in match.group(1).splitlines()
            if line.partition(":")[0].strip() not in _KEYS]
    body = text[match.end():]
    return "---\n" + "\n".join(kept) + "\n---\n" + body if kept else body


def content_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Hermes keeps its own copy: the plugin folder is installed against the published
# 0.5.0 core, which has no agentjury.local_store. tests/test_hermes_plugin.py pins the imports.
def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def frontmatter_lines(verdict: Verdict, digest: str | None = None) -> list[str]:
    lines = [
        f"agentjury_status: {verdict.status}",
        f"agentjury_votes: \"▲{verdict.up} ▼{verdict.down}\"",
        f"agentjury_score: {verdict.score}",
        f"agentjury_confidence: {verdict.confidence}",
        f"agentjury_request_id: {verdict.request_id}",
        f"agentjury_run_id: {verdict.run_id}",
        f"agentjury_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if digest:
        lines.append(f"agentjury_content_sha256: {digest}")
    return lines


def write_frontmatter(path: Path, verdict: Verdict, expected_digest: str | None = None) -> bool:
    """Upsert agentjury_* keys into a markdown file's YAML frontmatter. Creates one if absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    digest = content_digest(stripped_content(text))
    if expected_digest is not None and digest != expected_digest:
        return False
    new = frontmatter_lines(verdict, digest)
    m = _FM.match(text)
    if m:
        kept = [ln for ln in m.group(1).splitlines() if ln.partition(":")[0].strip() not in _KEYS]
        body = text[m.end():]
        out = "---\n" + "\n".join(kept + new) + "\n---\n" + body
    else:
        out = "---\n" + "\n".join(new) + "\n---\n" + text
    # Recheck just before replacement. External writers cannot participate in
    # this plugin's lock; the stored digest identifies the certified snapshot.
    if content_digest(stripped_content(path.read_text(encoding="utf-8"))) != digest:
        return False
    atomic_write(path, out)
    return True


def write_sidecar(path: Path, verdict: Verdict) -> Path:
    side = path.with_suffix(path.suffix + ".agentjury.json")
    atomic_write(side, verdict.model_dump_json(indent=2))
    return side


def invalidate_annotation(path: Path) -> None:
    """Remove current-file certification while retaining saved historical verdicts."""
    path.with_suffix(path.suffix + ".agentjury.json").unlink(missing_ok=True)
    if path.suffix.lower() != ".md" or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    clean = stripped_content(text)
    if clean != text and path.read_text(encoding="utf-8") == text:
        atomic_write(path, clean)


# Separate from agentjury.display for the same 0.5.0 compatibility reason.
def render_verdict(verdict: Verdict, files: list[str] | None = None) -> str:
    lines = [f"{verdict.render()}   run {verdict.run_id}",
             f"jury confidence index {verdict.confidence:.0%}"]
    for r in verdict.reviews:
        arrow = {"approve": "▲", "revise": "▼", "abstain": "–"}[r.vote]
        # Model-written text must not reach the terminal unescaped.
        lines.append(f"{arrow} {r.score:.0f}  {escape_controls(r.judge)}: {escape_controls(r.reason)}")
        for i, f in enumerate(r.findings, 1):
            lines.append(f"      {i}. [{f.severity}] {escape_controls(f.text)}")
    for e in verdict.errors:
        lines.append(f"!  {escape_controls(e)}")
    for signal in verdict.local_signals:
        lines.append(f"Local check [{signal.rule_id}]: {escape_controls(signal.excerpt)}")
    for artifact in verdict.artifact_coverage:
        lines.append(f"artifact {artifact.name}: {artifact.coverage}; annotation {artifact.annotation_status}")
    if files:
        lines.append("files: " + ", ".join(files))
    lines.append(f"adjudicate: agentjury adjudicate {verdict.run_id} --dir <hermes-home>/plugin-data/agentjury/verdicts ...")
    return "\n".join(lines)


def feedback_text(verdict: Verdict) -> str:
    """What the model sees at the start of the next turn if the last verdict was not verified."""
    findings = [
        f"- [{f.severity}] ({r.judge}) {f.text}"
        for r in verdict.reviews for f in r.findings if f.severity != "minor"
    ] or [f"- ({r.judge}) {r.reason}" for r in verdict.reviews if r.vote == "revise"]
    points = "Independent reviewers raised these points:\n" + "\n".join(findings[:8]) if findings else ""
    checks = "\n".join(f"Local check [{signal.rule_id}]: {signal.excerpt}" for signal in verdict.local_signals)
    return (
        f"AgentJury peer review of your previous response: {verdict.render()}.\n"
        + "\n".join(part for part in (points, checks) if part) +
        "\nIf the user is continuing the same task, address these. Do not mention this note unless asked."
    )


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class TurnFiles:
    paths: list[str] = field(default_factory=list)


@dataclass
class CapturedFile:
    path: str
    generation: int
    coverage: ArtifactCoverage


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
        self.file_generations: dict[str, int] = {}
        # Every turn in a session gets an increasing sequence number. A review may
        # finish out of order; only the highest-sequence finished review is "latest".
        self.turn_seq: dict[str, int] = {}
        self.latest_seq: dict[str, int] = {}
        self.pending: dict[tuple[str, int], Future] = {}
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
                p = os.path.normcase(str(Path(p).resolve()))
                with self._lock:
                    self.file_generations[p] = self.file_generations.get(p, 0) + 1
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
            seq = self.turn_seq.get(session_id, 0) + 1
            self.turn_seq[session_id] = seq
            generations = {path: self.file_generations[path] for path in paths}
        artifacts = []
        captured = []
        for index, path in enumerate(paths):
            artifact = read_artifact(path) if index < MAX_ARTIFACTS else None
            if artifact is not None:
                artifacts.append(artifact)
                coverage = ArtifactCoverage(artifact_id=artifact.artifact_id, name=path,
                    content_sha256=artifact.content_sha256, coverage=artifact.coverage)
            else:
                coverage = ArtifactCoverage(name=path, coverage="omitted" if index >= MAX_ARTIFACTS else "unavailable")
            captured.append(CapturedFile(path, generations[path], coverage))
        request = ReviewRequest(
            task=user_message or "(no user message captured)",
            output=assistant_response,
            context=self.context,
            task_type=self.settings.task_type or None,
            domain=self.settings.domain or None,
            artifacts=artifacts,
            producer=Producer(agent="hermes", framework="hermes", provider=infer_provider(model), model=model),
        )
        key = (session_id, seq)
        fut = self._pool.submit(self._review, session_id, seq, request, captured)
        self.pending[key] = fut
        # If the review already finished, this runs immediately; otherwise on completion.
        # Either way the entry is removed exactly once, with no window for a stale one.
        fut.add_done_callback(lambda _f, k=key: self.pending.pop(k, None))
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

    def _review(self, session_id: str, seq: int, request: ReviewRequest, captured: list[CapturedFile]) -> Verdict:
        try:
            return self._review_inner(session_id, seq, request, captured)
        except Exception:
            log.exception("agentjury: review failed for session %s turn %d", session_id, seq)
            raise

    def _review_inner(self, session_id: str, seq: int, request: ReviewRequest, captured: list[CapturedFile]) -> Verdict:
        with self._lock:
            if self._panel is None:
                self._panel = self._panel_factory(self.settings)
            panel = self._panel
        verdict = panel.review(request)
        verdict.artifact_coverage = [item.coverage for item in captured]
        paths = [item.path for item in captured]
        with self._lock:
            sidecars = []
            for item in captured:
                coverage = item.coverage
                path = Path(item.path)
                if self.file_generations.get(item.path) != item.generation:
                    coverage.annotation_status = "stale"
                    continue
                try:
                    if coverage.coverage != "full":
                        coverage.annotation_status = coverage.coverage
                        invalidate_annotation(path)
                        continue
                    digest = content_digest(stripped_content(path.read_text(encoding="utf-8")))
                    if digest != coverage.content_sha256:
                        coverage.annotation_status = "changed"
                        invalidate_annotation(path)
                        continue
                    frontmatter = self.settings.frontmatter and path.suffix.lower() == ".md"
                    if not self.settings.sidecar and not frontmatter:
                        coverage.annotation_status = "not_requested"
                        continue
                    coverage.annotation_status = "applied"
                    if frontmatter and not write_frontmatter(path, verdict, coverage.content_sha256):
                        coverage.annotation_status = "changed"
                        invalidate_annotation(path)
                        continue
                    if self.settings.sidecar:
                        sidecars.append(item)
                except (OSError, UnicodeError):
                    coverage.annotation_status = "write_failed"
                    try:
                        invalidate_annotation(path)
                    except (OSError, UnicodeError):
                        log.warning("agentjury: could not remove superseded certification %s", path)
                    log.warning("agentjury: could not annotate %s", path)
            # Publish only after every coverage/frontmatter result is known.
            # If one publication fails, remove that target and republish the
            # others with final statuses. Each failure removes a target, so
            # this loop terminates even while external files keep changing.
            while sidecars:
                failed = []
                for item in sidecars:
                    path = Path(item.path)
                    try:
                        if content_digest(stripped_content(path.read_text(encoding="utf-8"))) != item.coverage.content_sha256:
                            item.coverage.annotation_status = "changed"
                            invalidate_annotation(path)
                            failed.append(item)
                        else:
                            write_sidecar(path, verdict)
                    except (OSError, UnicodeError):
                        item.coverage.annotation_status = "write_failed"
                        try:
                            # A prior sidecar may match the same body but refer
                            # to a different task and an obsolete approval.
                            path.with_suffix(path.suffix + ".agentjury.json").unlink(missing_ok=True)
                        except OSError:
                            log.warning("agentjury: could not remove superseded sidecar %s", path)
                        failed.append(item)
                        log.warning("agentjury: could not publish sidecar %s", path)
                if not failed:
                    break
                sidecars = [item for item in sidecars if item not in failed]
            atomic_write(self.verdict_dir / verdict.filename, verdict.model_dump_json(indent=2))
            if seq >= self.latest_seq.get(session_id, 0):
                self.latest_seq[session_id] = seq
                self.last[session_id] = verdict
                self.last_files[session_id] = paths
                if verdict.status != "verified":
                    self.unread_feedback.add(session_id)
                else:
                    self.unread_feedback.discard(session_id)
            else:
                log.info("agentjury: turn %d finished after turn %d; saved but not made latest",
                         seq, self.latest_seq[session_id])
        log.info("agentjury: turn %d %s  %s", seq, verdict.render(), ", ".join(paths))
        return verdict

    # -- slash command -------------------------------------------------------

    def status(self, raw_args: str = "") -> str:
        arg = raw_args.strip()
        if arg:
            hits = [f for f in self.verdict_dir.glob("*.json") if arg in f.stem]
            if len(hits) == 1:
                return render_verdict(Verdict.model_validate_json(hits[0].read_text(encoding="utf-8")))
            return f"{len(hits)} verdicts match {arg!r}. Saved verdicts are in {self.verdict_dir}"
        running = [k for k, fut in self.pending.items() if not fut.done()]
        if running and not self.last:
            return f"AgentJury: {len(running)} review(s) in progress..."
        if not self.last:
            return f"AgentJury: no verdicts yet. Panel: {self.settings.panel}"
        session = max(self.last, key=lambda s: self.last[s].created_at)
        head = "(review in progress for the latest turn)\n" if running else ""
        return head + render_verdict(self.last[session], self.last_files.get(session))

    def wait(self, timeout: float | None = None) -> None:
        for fut in list(self.pending.values()):
            fut.result(timeout=timeout)
