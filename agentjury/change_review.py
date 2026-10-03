"""
Explicit, confirmed AgentJury reviews of Git code changes.

    agentjury change candidates            list changed files; reads no contents
    agentjury change prepare ...           build and preview a review locally; sends nothing
    agentjury change send ID --confirm C   send one prepared review, then save its verdict
    agentjury change status [RUN]          show a saved review and whether its code is unchanged

Only `send` contacts reviewers, and it refuses unless the payload, the reviewed
files and the reviewer configuration are exactly what was previewed. Verdicts
are ordinary AgentJury verdicts: aggregation, quorum, provider diversity,
blocking and adjudication are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from . import __version__, panel_config
from .change_secrets import scan
from .change_snapshot import (
    DEFAULT_CONTEXT_LINES, MAX_FILE_CHARS, MAX_READ_BYTES, MAX_TOTAL_CHARS, SECRET_REASON, STATE_DIR,
    ChangeError, ChangeSnapshot, SkipFile, capture, changed_since, find_candidates, head_commit,
    is_ignored, matches_commit, read_worktree, repo_relative, repo_root, resolve_commit, secret_named,
    select, sha256,
)
from .judges import ROLES, register_roles
from .judges.base import build_system_prompt, build_user_prompt
from .judges.evidence import _normalize
from .panel import Panel
from .protocol import ArtifactCoverage, Producer, ReviewRequest, Verdict
from .reviewer_guard import escape_controls

DEFAULT_CHANGE_PANEL = "correctness:openai,security:anthropic,tests:openai"
EXIT_REFUSED = 6
EXIT_STALE = 7
VERDICT_EXIT = {"verified": 0, "needs_revision": 1, "blocked": 2, "insufficient_jury": 3}
CONFIRM_CHARS = 16
MAX_TASK_CHARS = 20_000
MAX_LOG_CHARS = 20_000
CHANGES_DIR = Path(STATE_DIR) / "changes"


def code_roles() -> dict[str, str]:
    """The packaged code-review roles: correctness, security and tests."""
    raw = resources.files("agentjury").joinpath("data/change_roles.json").read_text(encoding="utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Saved records
# ---------------------------------------------------------------------------


class Destination(BaseModel):
    """One reviewer that will receive the payload. Never holds a key."""

    model_config = ConfigDict(extra="forbid")

    judge: str
    role: str
    provider: str
    route: str
    model: str
    host: str | None = None
    config_id: str


class SuppliedLog(BaseModel):
    """Test output supplied by the caller. AgentJury did not run the tests."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    chars_total: int
    chars_sent: int
    modified_at: datetime
    older_than_change: bool


class ChangeBundle(BaseModel):
    """A prepared review: exactly what `send` will submit, and the code it covers."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["agentjury.change.bundle"] = "agentjury.change.bundle"
    version: Literal[1] = 1
    agentjury_version: str
    created_at: datetime
    request: ReviewRequest
    snapshot: ChangeSnapshot
    task_file: str | None = None
    test_log: SuppliedLog | None = None
    allowed_secrets: list[str] = []
    panel: str
    quorum: int
    roles: dict[str, str]
    destinations: list[Destination]
    max_attempts: int
    payload_digest: str

    @property
    def confirm_code(self) -> str:
        return self.payload_digest[:CONFIRM_CHARS]


class ChangeReview(BaseModel):
    """A sent review: the bundle it came from and where its verdict is saved."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["agentjury.change.review"] = "agentjury.change.review"
    version: Literal[1] = 1
    run_id: str
    request_id: str
    sent_at: datetime
    verdict_file: str
    bundle: ChangeBundle


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _changes(root: Path) -> Path:
    return root / CHANGES_DIR


def pending_dir(root: Path, request_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", request_id):
        raise ChangeError(f"{request_id!r} is not a prepared review ID.")
    return _changes(root) / "pending" / request_id


def _ensure_state(root: Path) -> list[str]:
    """Create the local state directory and keep it out of Git. Returns warnings."""
    (root / STATE_DIR).mkdir(exist_ok=True)
    probe = f"{STATE_DIR}/changes/pending/probe"
    if is_ignored(root, probe):
        return []
    marker = root / STATE_DIR / ".gitignore"
    if not marker.exists():
        _atomic_write(marker, "# Created by AgentJury: keep local reviews, which contain code, out of Git.\n*\n")
        if is_ignored(root, probe):
            return []
    return [f"Git does not ignore {STATE_DIR}/. Add it to .gitignore: saved reviews contain code."]


def load_reviews(root: Path) -> list[ChangeReview]:
    folder = _changes(root) / "reviews"
    reviews = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            reviews.append(ChangeReview.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return reviews


def load_pending(root: Path) -> list[ChangeBundle]:
    folder = _changes(root) / "pending"
    bundles = []
    for path in sorted(folder.glob("*/bundle.json")) if folder.is_dir() else []:
        try:
            bundles.append(ChangeBundle.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return bundles


def _verdict_dir(args: argparse.Namespace, root: Path) -> Path:
    return Path(getattr(args, "dir", None) or os.environ.get("AGENTJURY_VERDICT_DIR")
                or root / STATE_DIR / "verdicts")


# ---------------------------------------------------------------------------
# Reviewers and payload identity
# ---------------------------------------------------------------------------


def build_panel(spec: str, quorum: int | None = None) -> Panel:
    """Construct the configured reviewers without contacting a provider. Tests replace this."""
    return panel_config.build_panel(spec, quorum=quorum)


def _panel(spec: str, quorum: int | None, roles: dict[str, str]) -> Panel:
    try:
        register_roles(roles)
        return build_panel(spec, quorum)
    except ValueError as exc:
        raise ChangeError(f"Invalid reviewer panel: {exc}") from None
    except ImportError as exc:
        message = str(exc)
        raise ChangeError(message if "package is not installed. Run: pip install" in message
                          else "Could not load a reviewer panel dependency.") from None
    except Exception as exc:  # noqa: BLE001 - SDK constructors raise their own error types
        raise ChangeError(f"Could not set up the reviewer panel ({type(exc).__name__}). "
                          "Check provider API keys and endpoint settings.") from None


def _host(judge: object) -> str | None:
    for value in (getattr(judge, "_api_url", None), getattr(judge, "base_url", None),
                  getattr(getattr(judge, "_client", None), "base_url", None)):
        if value is None:
            continue
        try:
            parts = urlsplit(str(value))
            if parts.hostname:
                return parts.hostname + (f":{parts.port}" if parts.port else "")
        except ValueError:
            continue
    return None


def destinations(panel: Panel) -> list[Destination]:
    return [
        Destination(judge=judge.name, role=judge.role, provider=judge.provider,
                    route=str(judge.params.get("route") or judge.provider), model=judge.model,
                    host=_host(judge), config_id=judge.config_id)
        for judge in panel.judges
    ]


def payload_digest(request: ReviewRequest, reviewers: list[Destination], quorum: int) -> str:
    """SHA-256 of what every reviewer receives and of who receives it."""
    material = {
        "kind": "agentjury.change.payload",
        "version": 1,
        "user_prompt": build_user_prompt(request),
        "reviewers": [d.model_dump(include={"judge", "route", "model", "host", "config_id"})
                      for d in reviewers],
        "quorum": quorum,
        "record": {"task_type": request.task_type, "domain": request.domain,
                   "producer": request.producer.model_dump(mode="json")},
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def coverage(snapshot: ChangeSnapshot) -> list[ArtifactCoverage]:
    return [
        ArtifactCoverage(name=item.path, content_sha256=item.sha256 if item.reviewed else None,
                         coverage="full" if item.reviewed else "omitted",
                         annotation_status="not_requested")
        for item in snapshot.files
    ]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_log(text: str) -> str:
    """Remove terminal colour codes and other control characters from captured output."""
    text = _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL.sub("", text)


def _input_file(raw: str, root: Path, cwd: Path, what: str) -> tuple[str, bytes]:
    rel = repo_relative(raw, root, cwd)
    if not rel:
        raise ChangeError(f"The {what} must be a file inside the repository.")
    if secret_named(rel):
        raise ChangeError(f"Refusing to read {rel} as the {what}: {SECRET_REASON.split(';')[0]}.")
    try:
        data = read_worktree(root, rel, MAX_READ_BYTES)
    except SkipFile as exc:
        raise ChangeError(f"Cannot read the {what} {rel}: {exc}.") from None
    if data is None:
        raise ChangeError(f"The {what} {raw!r} does not exist.")
    return rel, data


def _task(args: argparse.Namespace, root: Path, cwd: Path) -> tuple[str, str | None]:
    if args.task is not None:
        text, source = args.task, None
    elif args.task_file == "-":
        text, source = sys.stdin.read(), "-"
    else:
        source, data = _input_file(args.task_file, root, cwd, "task file")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ChangeError("The task file is not UTF-8 text.") from None
    text = text.strip()
    if not text:
        raise ChangeError("The task is empty. Describe what the change was supposed to do.")
    if len(text) > MAX_TASK_CHARS:
        raise ChangeError(f"The task has {len(text):,} characters; the limit is {MAX_TASK_CHARS:,}.")
    return text, source


def _test_log(raw: str, root: Path, cwd: Path, snapshot: ChangeSnapshot) -> tuple[SuppliedLog, str]:
    rel, data = _input_file(raw, root, cwd, "test log")
    text = clean_log(data.decode("utf-8", "replace")).rstrip("\n")
    total = len(text)
    if total > MAX_LOG_CHARS:
        tail = text[-MAX_LOG_CHARS:]
        cut = tail.find("\n")
        tail = tail[cut + 1:] if 0 <= cut < 2_000 else tail
        text = f"[... {total - len(tail):,} earlier characters omitted ...]\n{tail}"
    modified = os.stat(root / rel).st_mtime
    edits = []
    for item in snapshot.reviewed:
        try:
            edits.append(os.lstat(root / item.path).st_mtime)
        except OSError:
            continue
    log = SuppliedLog(path=rel, sha256=sha256(data), chars_total=total, chars_sent=len(text),
                      modified_at=datetime.fromtimestamp(modified, timezone.utc),
                      older_than_change=bool(edits) and modified < max(edits))
    return log, text


def build_context(snapshot: ChangeSnapshot, log: SuppliedLog | None, log_text: str | None) -> str:
    reviewed, omitted = snapshot.reviewed, snapshot.omitted
    lines = [
        "REVIEW SCOPE (prepared by AgentJury from the repository, not written by the agent)",
        f"The diff compares the working tree, including uncommitted edits, with commit "
        f"{snapshot.base_commit[:12]} ({snapshot.base}).",
        f"Reviewed files ({len(reviewed)}): "
        + "; ".join(f"{f.path} ({f.change}, +{f.added} -{f.removed})" for f in reviewed),
    ]
    if omitted:
        lines.append(f"Changed files not included ({len(omitted)}): "
                     + "; ".join(f"{f.path} ({f.reason})" for f in omitted))
    lines += ["Reviewers see only this diff and its context lines. They cannot run the code or open other files.",
              "", "TEST EVIDENCE"]
    if log is None:
        lines.append("None supplied.")
    else:
        lines.append(f"Supplied log {log.path}, modified {log.modified_at:%Y-%m-%d %H:%M} UTC. "
                     "AgentJury did not run these tests and cannot confirm that this output comes "
                     "from the reviewed code.")
        if log.older_than_change:
            lines.append("Warning: the log is older than the latest edit to a reviewed file.")
        lines += ["----- BEGIN TEST LOG -----", log_text or "", "----- END TEST LOG -----"]
    return "\n".join(lines)


def _roles_file(path: str) -> dict[str, str]:
    try:
        roles = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ChangeError(f"Cannot read roles file {path!r} as JSON.") from None
    if not isinstance(roles, dict) or not all(isinstance(v, str) for v in roles.values()):
        raise ChangeError("Roles file must be a JSON object mapping role names to descriptions.")
    return roles


def _check_limits(args: argparse.Namespace) -> None:
    if not 0 <= args.context_lines <= 100:
        raise ChangeError("--context-lines must be between 0 and 100.")
    if args.max_file_chars < 1 or args.max_total_chars < 1:
        raise ChangeError("Character limits must be positive.")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return escape_controls(str(value))


def _cell(value: object) -> str:
    return _esc(value).replace("|", "\\|")


def _fenced(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _relative(path: Path, cwd: Path) -> str:
    try:
        rel = os.path.relpath(path, cwd)
    except ValueError:
        return str(path)
    return str(path) if rel.startswith(os.pardir) else rel


def _quote(value: str) -> str:
    return f'"{value}"' if any(ch.isspace() for ch in value) else value


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def preview_markdown(bundle: ChangeBundle) -> str:
    request, snapshot = bundle.request, bundle.snapshot
    lines = [
        "# AgentJury change review preview (not sent)",
        "",
        f"- Prepared review: `{request.request_id}`",
        f"- Confirmation code: `{bundle.confirm_code}`",
        f"- Payload SHA-256: `{bundle.payload_digest}`",
        f"- Prepared: {bundle.created_at:%Y-%m-%d %H:%M:%S} UTC",
        f"- Base: {_esc(snapshot.base)} ({snapshot.base_commit})",
        "",
        "Nothing in this file has been sent. `agentjury change send` sends the user prompt below,",
        "unchanged, to each reviewer listed here together with that reviewer's system prompt.",
        "No other repository content is sent.",
        "",
        "## Reviewers",
        "",
        "| Reviewer | Route | Model | Destination |",
        "| --- | --- | --- | --- |",
        *(f"| {_cell(d.judge)} | {_cell(d.route)} | {_cell(d.model)} | {_cell(d.host or 'SDK default')} |"
          for d in bundle.destinations),
        "",
        f"Quorum {bundle.quorum}; at most {bundle.max_attempts} provider requests including retries.",
        "",
        "## Files",
        "",
        "| File | Change | Sent | Note |",
        "| --- | --- | --- | --- |",
        *(f"| {_cell(f.path)} | {f.change} | {'yes' if f.reviewed else 'no'} | "
          f"{_cell(f'+{f.added} -{f.removed}' if f.reviewed else f.reason)} |" for f in snapshot.files),
        "",
        "## User prompt (identical for every reviewer)",
        "",
        _fenced(build_user_prompt(request)),
        "",
        "## System prompts",
    ]
    for role in dict.fromkeys(d.role for d in bundle.destinations):
        judges = ", ".join(d.judge for d in bundle.destinations if d.role == role)
        lines += ["", f"### Role `{_esc(role)}` ({_esc(judges)})", "", _fenced(build_system_prompt(role))]
    return "\n".join(lines) + "\n"


def manifest_lines(bundle: ChangeBundle, preview: Path, cwd: Path, warnings: list[str]) -> list[str]:
    snapshot = bundle.snapshot
    reviewed, omitted = snapshot.reviewed, snapshot.omitted
    chars = sum((f.diff_end or 0) - (f.diff_start or 0) for f in reviewed)
    lines = [
        "AgentJury change review prepared. Nothing has been sent.",
        "",
        f"Prepared review {bundle.request.request_id}   confirmation code {bundle.confirm_code}",
        f"Payload SHA-256 {bundle.payload_digest}",
        "",
        f"Reviewers ({len(bundle.destinations)}; quorum {bundle.quorum}; "
        f"at most {bundle.max_attempts} provider requests):",
        *(f"  {_esc(d.judge):<26} {_esc(d.route):<11} {_esc(d.model):<24} {_esc(d.host or 'SDK default endpoint')}"
          for d in bundle.destinations),
        "Each reviewer receives its role's AgentJury system prompt and the same user prompt.",
        "",
        f"Change: working tree against {_esc(snapshot.base)} ({snapshot.base_commit[:12]})",
        f"Sent ({_files(len(reviewed))}, +{sum(f.added or 0 for f in reviewed)} "
        f"-{sum(f.removed or 0 for f in reviewed)}, {chars:,} diff characters):",
        *(f"  {f.change:<12} {_esc(f.path)}  +{f.added} -{f.removed}" for f in reviewed),
    ]
    if omitted:
        lines.append("Not sent:")
        lines += [f"  {f.change:<12} {_esc(f.path)}  ({f.reason})" for f in omitted]
    log = bundle.test_log
    if log is None:
        lines.append("Test evidence: none supplied.")
    else:
        lines.append(f"Test evidence: {_esc(log.path)} ({log.chars_sent:,} of {log.chars_total:,} characters; "
                     "supplied, not run by AgentJury)")
        if log.older_than_change:
            lines.append("  Warning: the log is older than the latest edit to a reviewed file.")
    if bundle.allowed_secrets:
        lines.append("Secret scan: matches allowed by --allow-secret: " + ", ".join(map(_esc, bundle.allowed_secrets)))
    else:
        lines.append("Secret scan: no matches (heuristic; check the preview before sending).")
    lines += [f"Warning: {_esc(w)}" for w in warnings]
    lines += [
        "",
        f"Full payload: {_esc(_relative(preview, cwd))}",
        "",
        "To send, run this command yourself (in Claude Code, type it after !):",
        f"  agentjury change send {bundle.request.request_id} --confirm {bundle.confirm_code}",
    ]
    return lines


def _file_hints(bundle: ChangeBundle) -> list[tuple[str, str]]:
    output = bundle.request.output
    return [(f.path, _normalize(output[f.diff_start:f.diff_end])) for f in bundle.snapshot.reviewed
            if f.diff_start is not None and f.diff_end is not None]


def verdict_lines(verdict: Verdict, bundle: ChangeBundle) -> list[str]:
    """The verdict with findings numbered as `agentjury adjudicate` expects. Model text is escaped."""
    lines = [verdict.render(), f"jury confidence index {verdict.confidence:.0%}  (heuristic, not a probability)"]
    if verdict.status == "insufficient_jury":
        voters = verdict.responded - verdict.abstained
        providers = len({r.provider for r in verdict.reviews if r.vote != "abstain"})
        lines.append(f"Insufficient jury: {voters} of {verdict.requested} judges voted (quorum {verdict.quorum}), "
                     f"from {providers} provider(s). No verdict.")
    reviewed, omitted = bundle.snapshot.reviewed, bundle.snapshot.omitted
    note = f"Coverage: {_files(len(reviewed))} reviewed"
    if omitted:
        note += f"; {len(omitted)} not sent: " + ", ".join(f"{_esc(f.path)} ({f.reason})" for f in omitted)
    lines.append(note)
    if verdict.local_signals:
        lines.append("Local check changed verified to needs_revision: reviewer-directed instruction detected."
                     if verdict.local_guard_applied
                     else "Local check detected a reviewer-directed instruction; status unchanged.")
        lines += [f"  ! {signal.rule_id}: {_esc(signal.excerpt)}" for signal in verdict.local_signals]
    lines.append("")
    hints = _file_hints(bundle)
    for review in verdict.reviews:
        arrow = {"approve": "▲", "revise": "▼", "abstain": "–"}[review.vote]
        meta = f"{review.latency_ms / 1000:.1f}s" if review.latency_ms is not None else ""
        lines.append(f"{arrow} {review.score:>2.0f}  {_esc(review.judge):<22} {_esc(review.reason)}  [{meta}]")
        for number, finding in enumerate(review.findings, 1):
            where = ""
            evidence = finding.evidence
            if evidence is not None and evidence.output_artifact_id is None:
                quote = _normalize(evidence.output_quote)
                files = [path for path, text in hints if quote and quote in text]
                where = f"  ({_esc(files[0])})" if len(files) == 1 else ("  (several files)" if files else "")
            checked = " [excerpts checked]" if evidence is not None else ""
            graded = f" [graded {finding.adjudication}]" if finding.adjudication else ""
            lines.append(f"        {number}. [{finding.severity}] {_esc(finding.text)}{where}{checked}{graded}")
    lines += [f"!  {_esc(error)}" for error in verdict.errors]
    return lines


def _follow_up(review: ChangeReview, cwd: Path) -> list[str]:
    folder = _quote(_relative(Path(review.verdict_file).parent, cwd))
    return [
        f"Saved verdict: {_esc(_relative(Path(review.verdict_file), cwd))}",
        "Grade findings yourself (numbers as shown): "
        f"agentjury adjudicate {review.run_id} --dir {_esc(folder)} --judge <judge> "
        "--finding <N> correct|partially_correct|wrong",
        f"Check later whether the reviewed code changed: agentjury change status {review.run_id}",
    ]


def _fail(exc: ChangeError, consequence: str) -> int:
    print(f"Refused: {_esc(exc)} {consequence}".rstrip(), file=sys.stderr)
    for detail in exc.details:
        print(f"  {_esc(detail)}", file=sys.stderr)
    return EXIT_REFUSED


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_candidates(args: argparse.Namespace) -> int:
    try:
        root = repo_root(Path.cwd())
        base_commit = resolve_commit(root, args.base)
        items = find_candidates(root, base_commit)
    except ChangeError as exc:
        return _fail(exc, "")
    if args.json:
        print(json.dumps({"root": str(root), "base": args.base, "base_commit": base_commit,
                          "files": [{"path": c.path, "change": c.change, "tracked": c.tracked,
                                     "not_sent": c.exclusion} for c in items]}, indent=2))
        return 0
    print(f"Changed files against {_esc(args.base)} ({base_commit[:12]}) in {_esc(root)}:")
    for c in items:
        label = c.change if c.tracked else "untracked"
        line = f"  {label:<12} {_esc(c.path)}"
        print(line + (f"  [not sent: {c.exclusion}]" if c.exclusion else ""))
    if not items:
        print("  (none)")
    print("Binary, non-UTF-8 and oversized files are reported by `agentjury change prepare`.")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        _check_limits(args)
        root = repo_root(cwd)
        task, task_source = _task(args, root, cwd)
        base_commit = resolve_commit(root, args.base)
        candidates = find_candidates(root, base_commit)
        if not candidates:
            raise ChangeError(f"No changed files against {args.base}.")
        snapshot, diff = capture(
            root, args.base, base_commit, select(candidates, args.path, root, cwd),
            context_lines=args.context_lines, max_file_chars=args.max_file_chars,
            max_total_chars=args.max_total_chars,
        )
        if not snapshot.reviewed:
            raise ChangeError("Nothing to review: every selected file is excluded.",
                              [f"{f.path}: {f.reason}" for f in snapshot.omitted])
        log, log_text = _test_log(args.test_log, root, cwd, snapshot) if args.test_log else (None, None)

        sources = [("task", task)]
        sources += [(f"diff:{f.path}", diff[f.diff_start:f.diff_end]) for f in snapshot.reviewed]
        if log_text is not None:
            sources.append(("test-log", log_text))
        allowed = set(args.allow_secret or [])
        matches = scan(sources)
        blocking = [m for m in matches if m.id not in allowed]
        if blocking:
            raise ChangeError(
                "Possible secrets found in text that would be sent.",
                [m.describe() for m in blocking] + [
                    "Remove the secret or leave its file out of --path. If a match is a false positive, "
                    "repeat the command with --allow-secret <id> for that match."],
            )

        request = ReviewRequest(
            task=task, output=diff, context=build_context(snapshot, log, log_text),
            task_type=args.task_type or None, domain=args.domain,
            producer=Producer(agent=args.agent, framework=args.framework,
                              provider=args.producer_provider, model=args.producer_model),
        )
        roles = code_roles()
        if args.roles:
            roles.update(_roles_file(args.roles))
        panel = _panel(args.panel, args.quorum, roles)
        reviewers = destinations(panel)
        bundle = ChangeBundle(
            agentjury_version=__version__, created_at=_now(), request=request, snapshot=snapshot,
            task_file=task_source, test_log=log, allowed_secrets=sorted(m.id for m in matches if m.id in allowed),
            panel=args.panel, quorum=panel.quorum, roles={j.role: ROLES[j.role] for j in panel.judges},
            destinations=reviewers, max_attempts=sum(2 * (j.retries + 1) for j in panel.judges),
            payload_digest=payload_digest(request, reviewers, panel.quorum),
        )
        warnings = _ensure_state(root)
        folder = pending_dir(root, request.request_id)
        _atomic_write(folder / "bundle.json", bundle.model_dump_json(indent=2))
        preview = folder / "preview.md"
        _atomic_write(preview, preview_markdown(bundle))
    except ChangeError as exc:
        return _fail(exc, "Nothing was saved or sent.")

    if args.json:
        print(json.dumps({
            "prepared": request.request_id, "confirmation_code": bundle.confirm_code,
            "payload_sha256": bundle.payload_digest, "preview": str(preview),
            "send_command": f"agentjury change send {request.request_id} --confirm {bundle.confirm_code}",
            "reviewers": [d.model_dump() for d in reviewers],
            "files": [f.model_dump(include={"path", "change", "reviewed", "reason", "added", "removed"})
                      for f in snapshot.files],
            "warnings": warnings,
        }, indent=2))
    else:
        print("\n".join(manifest_lines(bundle, preview, cwd, warnings)))
    return 0


def _verify(args: argparse.Namespace, root: Path, bundle: ChangeBundle) -> Panel:
    if args.confirm.strip().lower() != bundle.confirm_code:
        raise ChangeError("The confirmation code does not match this prepared review.")
    if payload_digest(bundle.request, bundle.destinations, bundle.quorum) != bundle.payload_digest:
        raise ChangeError("The prepared review was edited after its preview. Prepare it again.")
    changed = changed_since(root, bundle.snapshot)
    if changed:
        raise ChangeError("Reviewed files changed after the preview. Prepare the review again.",
                          [f"{path}: {how}" for path, how in changed])
    if not args.allow_repeat:
        for review in load_reviews(root):
            if review.bundle.payload_digest == bundle.payload_digest:
                raise ChangeError(f"An identical review was already sent as run {review.run_id}. "
                                  "Use --allow-repeat to send it again.")
    panel = _panel(bundle.panel, bundle.quorum, bundle.roles)
    if destinations(panel) != bundle.destinations or panel.quorum != bundle.quorum:
        raise ChangeError("The reviewer configuration changed after the preview (panel, roles, models, "
                          "endpoints or settings). Prepare the review again.")
    return panel


def cmd_send(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        root = repo_root(cwd)
        folder = pending_dir(root, args.id)
        bundle_file = folder / "bundle.json"
        if not bundle_file.is_file():
            sent = [r for r in load_reviews(root) if r.request_id == args.id]
            if sent:
                raise ChangeError(f"Prepared review {args.id} was already sent as run {sent[0].run_id}. "
                                  "Prepare a new review to send again.")
            raise ChangeError(f"No prepared review {args.id}. Run `agentjury change prepare` first.")
        try:
            bundle = ChangeBundle.model_validate_json(bundle_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ChangeError("The prepared review is unreadable or was edited. Prepare it again.") from None
        if bundle.request.request_id != args.id:
            raise ChangeError("The prepared review does not match its ID. Prepare it again.")
        lock = folder / ".sending"
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            raise ChangeError(f"Prepared review {args.id} is being sent, or an earlier send was interrupted. "
                              "Prepare a new review.") from None
        try:
            panel = _verify(args, root, bundle)
        except ChangeError:
            lock.unlink(missing_ok=True)
            raise
    except ChangeError as exc:
        return _fail(exc, "Nothing was sent.")

    if not args.json:
        print(f"Sending prepared review {args.id} to {len(panel.judges)} reviewers "
              f"(at most {bundle.max_attempts} provider requests)...", flush=True)
    verdict = panel.review(bundle.request)
    verdict.artifact_coverage = coverage(bundle.snapshot)
    try:
        verdict_path = _verdict_dir(args, root) / verdict.filename
        _atomic_write(verdict_path, verdict.model_dump_json(indent=2))
        review = ChangeReview(run_id=verdict.run_id, request_id=bundle.request.request_id, sent_at=_now(),
                              verdict_file=str(verdict_path.resolve()), bundle=bundle)
        _atomic_write(_changes(root) / "reviews" / f"{verdict.run_id}.json", review.model_dump_json(indent=2))
        shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        print(verdict.model_dump_json(indent=2))
        print("Error: the review was sent but could not be saved; its verdict JSON is printed above.",
              file=sys.stderr)
        return EXIT_REFUSED

    if args.json:
        print(verdict.model_dump_json(indent=2))
    else:
        print("\n".join(["", *verdict_lines(verdict, bundle), "",
                         "Code snapshot: CURRENT (reviewed files unchanged since the preview).",
                         *_follow_up(review, cwd)]))
    return VERDICT_EXIT[verdict.status]


def _pick(reviews: list[ChangeReview], ref: str | None) -> ChangeReview:
    if not ref:
        return max(reviews, key=lambda r: r.sent_at)
    exact = [r for r in reviews if ref in (r.run_id, r.request_id)]
    matches = exact or [r for r in reviews if ref in r.run_id or ref in r.request_id]
    if len(matches) != 1:
        raise ChangeError(f"{len(matches)} sent change reviews match {ref!r}.",
                          [f"run {r.run_id}  request {r.request_id}  sent {r.sent_at:%Y-%m-%d %H:%M}"
                           for r in matches[:10]])
    return matches[0]


def _status_notes(root: Path, snapshot: ChangeSnapshot) -> list[str]:
    notes = []
    head = head_commit(root)
    if head and snapshot.head_commit and head != snapshot.head_commit:
        notes.append(f"HEAD moved from {snapshot.head_commit[:12]} to {head[:12]} after the review.")
    if head and matches_commit(root, snapshot, head):
        notes.append(f"The reviewed content matches HEAD ({head[:12]}).")
    try:
        current = find_candidates(root, snapshot.base_commit)
    except ChangeError:
        current = []
    included = {f.path for f in snapshot.files}
    uncovered = [c.path for c in current if c.path not in included]
    if uncovered:
        shown = ", ".join(_esc(path) for path in uncovered[:10]) + (" ..." if len(uncovered) > 10 else "")
        notes.append(f"{len(uncovered)} other changed file(s) are not covered by this review: {shown}")
    return notes


def cmd_status(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        root = repo_root(cwd)
        reviews = load_reviews(root)
        if not reviews:
            pending = load_pending(root)
            if args.json:
                print(json.dumps({"reviews": 0, "pending": [b.request.request_id for b in pending]}, indent=2))
                return 0
            print("No sent change reviews in this repository.")
            for bundle in pending:
                print(f"Prepared, not sent: {bundle.request.request_id} ({bundle.created_at:%Y-%m-%d %H:%M} UTC)")
            return 0
        review = _pick(reviews, args.run)
        snapshot = review.bundle.snapshot
        changed = changed_since(root, snapshot)
        notes = _status_notes(root, snapshot)
    except ChangeError as exc:
        return _fail(exc, "")

    verdict_path = Path(review.verdict_file)
    if not verdict_path.is_file():
        verdict_path = _verdict_dir(args, root) / f"{review.request_id}-{review.run_id}.json"
    try:
        verdict = Verdict.model_validate_json(verdict_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        verdict = None

    if args.json:
        print(json.dumps({
            "run_id": review.run_id, "request_id": review.request_id,
            "sent_at": review.sent_at.isoformat(), "verdict_file": str(verdict_path),
            "verdict_status": verdict.status if verdict else None,
            "snapshot": "stale" if changed else "current",
            "changed": [{"path": path, "change": how} for path, how in changed],
            "notes": notes,
        }, indent=2))
        return EXIT_STALE if changed else 0

    lines = [f"AgentJury change review: run {review.run_id}, request {review.request_id}, "
             f"sent {review.sent_at:%Y-%m-%d %H:%M} UTC"]
    if changed:
        lines.append("Code snapshot: STALE. Changed after the review: "
                     + ", ".join(f"{_esc(path)} ({how})" for path, how in changed)
                     + ". Prepare a new review for the current code.")
    else:
        lines.append(f"Code snapshot: CURRENT. Reviewed: {_files(len(snapshot.reviewed))}, unchanged since the review.")
    lines += notes
    lines.append("")
    if verdict is None:
        lines.append(f"Verdict file not found or unreadable: {_esc(verdict_path)}")
    else:
        lines += verdict_lines(verdict, review.bundle)
        lines.append("")
        lines += _follow_up(review.model_copy(update={"verdict_file": str(verdict_path)}), cwd)
    print("\n".join(lines))
    return EXIT_STALE if changed else 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    """The `agentjury change` command group."""
    change = sub.add_parser("change", help="Review a Git code change: list, prepare and preview, send once, check status.")
    commands = change.add_subparsers(dest="change_command", required=True)

    c = commands.add_parser("candidates", help="List changed files and default exclusions. Reads no file contents.")
    c.add_argument("--base", default="HEAD", help="Commit to compare the working tree with (default: HEAD).")
    c.add_argument("--json", action="store_true", help="Print structured data.")
    c.set_defaults(func=cmd_candidates)

    p = commands.add_parser("prepare", help="Build and preview a review locally. Sends nothing.")
    task = p.add_mutually_exclusive_group(required=True)
    task.add_argument("--task", help="What the change was supposed to do.")
    task.add_argument("--task-file", help="UTF-8 file inside the repository with the task, or - for stdin.")
    p.add_argument("--path", action="append", default=[], metavar="PATH",
                   help="Changed file or directory to include; repeatable (default: every changed file).")
    p.add_argument("--base", default="HEAD", help="Commit to compare the working tree with (default: HEAD).")
    p.add_argument("--context-lines", type=int, default=DEFAULT_CONTEXT_LINES,
                   help=f"Unchanged lines around each change (default: {DEFAULT_CONTEXT_LINES}).")
    p.add_argument("--test-log", help="Test output file inside the repository; supplied evidence, not run by AgentJury.")
    p.add_argument("--panel", default=os.environ.get("AGENTJURY_CHANGE_PANEL", DEFAULT_CHANGE_PANEL),
                   help=f"role:provider[:model] entries (default: $AGENTJURY_CHANGE_PANEL or {DEFAULT_CHANGE_PANEL}).")
    p.add_argument("--roles", default=os.environ.get("AGENTJURY_ROLES"),
                   help="JSON file of extra roles; the packaged correctness, security and tests roles are always available.")
    p.add_argument("--quorum", type=int, help="Minimum judges that must vote (default: majority).")
    p.add_argument("--allow-secret", action="append", default=[], metavar="ID",
                   help="Accept one reported secret-scan match by its ID for this preparation; repeatable.")
    p.add_argument("--task-type", default="code_change", help="Kind of work recorded on the verdict (default: code_change).")
    p.add_argument("--domain", help="Subject area recorded on the verdict, e.g. python.")
    p.add_argument("--agent", help="Name of the agent that made the change.")
    p.add_argument("--framework", help="Framework the agent runs on, e.g. claude-code.")
    p.add_argument("--producer-provider", help="Provider of the model that made the change.")
    p.add_argument("--producer-model", help="Model that made the change.")
    p.add_argument("--max-file-chars", type=int, default=MAX_FILE_CHARS,
                   help=f"Leave out a file whose diff is longer (default: {MAX_FILE_CHARS:,}).")
    p.add_argument("--max-total-chars", type=int, default=MAX_TOTAL_CHARS,
                   help=f"Refuse a selection whose diff is longer (default: {MAX_TOTAL_CHARS:,}).")
    p.add_argument("--json", action="store_true", help="Print structured data instead of the manifest.")
    p.set_defaults(func=cmd_prepare)

    s = commands.add_parser("send", help="Send one prepared review to its reviewers and save the verdict.")
    s.add_argument("id", metavar="ID", help="Prepared review ID printed by prepare.")
    s.add_argument("--confirm", required=True, metavar="CODE", help="Confirmation code printed by prepare.")
    s.add_argument("--allow-repeat", action="store_true", help="Send even if an identical review was already sent.")
    s.add_argument("--dir", help="Verdict directory (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts in the repository).")
    s.add_argument("--json", action="store_true", help="Print the verdict as JSON.")
    s.set_defaults(func=cmd_send)

    t = commands.add_parser("status", help="Show a sent change review and whether its code changed since.")
    t.add_argument("run", nargs="?", metavar="RUN", help="run_id or request_id (or a unique fragment); default: latest.")
    t.add_argument("--dir", help="Verdict directory to search if the saved path moved.")
    t.add_argument("--json", action="store_true", help="Print structured data.")
    t.set_defaults(func=cmd_status)
