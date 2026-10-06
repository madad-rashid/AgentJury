"""
Human grading support: what still needs a grade, a text-free export of the
grades that exist, and descriptive counts of them.

    agentjury adjudication pending [--dir DIR]... [-n N] [--json]
    agentjury adjudication export  [--dir DIR]... [--out FILE]
    agentjury adjudication stats   [--dir DIR]... | --from EXPORT [--json]

These commands read saved verdicts and the adjudication log, contact nothing
and modify nothing. Nothing here weights a vote or changes a verdict: the
counts are descriptive, not reputation, and the aggregator never reads them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .cli import ADJUDICATION_LOG
from .local_store import atomic_write, verdict_dirs
from .protocol import Finding, Review, Verdict
from .reviewer_guard import escape_controls

EXPORT_KIND = "agentjury.adjudication.export"
EXPORT_VERSION = 1
EXIT_INVALID = 5
SEVERITY_RANK = {"blocking": 0, "major": 1, "minor": 2}
# Placeholders in printed commands are bare words that adjudicate rejects, never
# shell metacharacters: a command pasted unedited must record nothing.
LEGEND = "Replace LABEL with correct, partially_correct or wrong; GRADE with correct or flawed; VIEW with agree, partial or disagree."
CONFIDENCE_BANDS = ((0.75, "75-100%"), (0.5, "50-75%"), (0.25, "25-50%"), (0.0, "0-25%"))

# Reviewer parameters that may leave in an export, with the shape each value must have.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
_HEX = re.compile(r"^[0-9a-f]{12}$")
PARAM_SHAPES: dict[str, Any] = {
    "route": _SLUG, "transport": _SLUG, "format": _SLUG, "completion_policy": _SLUG,
    "effort": _SLUG, "thinking": _SLUG, "endpoint_hash": _HEX, "requested_model": _MODEL,
    "timeout": (int, float), "max_tokens": (int, float),
}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,31}$")  # semver and PEP 440 shapes
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
EVENT_KINDS = {"finding", "review", "producer"}
EVENT_FIELDS = ("event_id", "at", "kind", "run_id", "request_id", "review_id", "config_id", "judge",
                "finding_id", "old", "new")
GRADES = {"correct", "partially_correct", "wrong", "agree", "partial", "disagree", "flawed"}

# Every string an export may contain, by path (list indices and dynamic keys as "*").
# "free" values are operator-chosen labels that the export command discloses.
FREE = "free"
STRING_PATHS: dict[tuple[str, ...], Any] = {
    ("kind",): {EXPORT_KIND}, ("agentjury_version",): _VERSION, ("exported_at",): _TIMESTAMP,
    ("verdicts", "*", "run_id"): _ID, ("verdicts", "*", "request_id"): _ID, ("verdicts", "*", "panel_id"): _ID,
    ("verdicts", "*", "schema_version"): _VERSION, ("verdicts", "*", "created_at"): _TIMESTAMP,
    ("verdicts", "*", "adjudicated_at"): _TIMESTAMP,
    ("verdicts", "*", "task_type"): FREE, ("verdicts", "*", "domain"): FREE,
    ("verdicts", "*", "producer", "framework"): FREE, ("verdicts", "*", "producer", "provider"): FREE,
    ("verdicts", "*", "producer", "model"): FREE,
    ("verdicts", "*", "status"): {"verified", "needs_revision", "blocked", "insufficient_jury"},
    ("verdicts", "*", "local_signal_rules", "*"): {"force_approval", "score_override", "suppress_findings"},
    ("verdicts", "*", "errors", "*", "judge"): FREE, ("verdicts", "*", "errors", "*", "error"): _IDENT,
    ("verdicts", "*", "human_verdict"): {"correct", "flawed"},
    ("verdicts", "*", "reviews", "*", "review_id"): _ID, ("verdicts", "*", "reviews", "*", "config_id"): _ID,
    ("verdicts", "*", "reviews", "*", "judge"): FREE, ("verdicts", "*", "reviews", "*", "role"): FREE,
    ("verdicts", "*", "reviews", "*", "provider"): FREE, ("verdicts", "*", "reviews", "*", "model"): FREE,
    ("verdicts", "*", "reviews", "*", "observed_model"): FREE,
    ("verdicts", "*", "reviews", "*", "vote"): {"approve", "revise", "abstain"},
    ("verdicts", "*", "reviews", "*", "rubric_version"): _VERSION,
    ("verdicts", "*", "reviews", "*", "prompt_hash"): _ID,
    ("verdicts", "*", "reviews", "*", "created_at"): _TIMESTAMP,
    ("verdicts", "*", "reviews", "*", "human_review", "verdict"): {"agree", "partial", "disagree"},
    ("verdicts", "*", "reviews", "*", "human_review", "reviewed_at"): _TIMESTAMP,
    ("verdicts", "*", "reviews", "*", "findings", "*", "id"): _ID,
    ("verdicts", "*", "reviews", "*", "findings", "*", "severity"): {"minor", "major", "blocking"},
    ("verdicts", "*", "reviews", "*", "findings", "*", "basis_source"):
        {"task", "context", "output", "artifact", "reviewer_rule"},
    ("verdicts", "*", "reviews", "*", "findings", "*", "adjudication"): {"correct", "partially_correct", "wrong"},
    ("verdicts", "*", "reviews", "*", "findings", "*", "adjudicated_at"): _TIMESTAMP,
    ("events", "*", "event_id"): _ID, ("events", "*", "at"): _TIMESTAMP, ("events", "*", "kind"): EVENT_KINDS,
    ("events", "*", "run_id"): _ID, ("events", "*", "request_id"): _ID, ("events", "*", "review_id"): _ID,
    ("events", "*", "config_id"): _ID, ("events", "*", "judge"): FREE, ("events", "*", "finding_id"): _ID,
    ("events", "*", "old"): GRADES, ("events", "*", "new"): GRADES,
}
for _key, _shape in PARAM_SHAPES.items():
    if isinstance(_shape, re.Pattern):
        STRING_PATHS[("verdicts", "*", "reviews", "*", "params", _key)] = FREE if _key == "requested_model" else _shape


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass
class Loaded:
    """Verdicts and adjudication events from one or more verdict directories."""

    verdicts: list[tuple[Path, Verdict]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    unreadable: int = 0
    duplicates: int = 0
    orphan_events: int = 0


def _grading_progress(verdict: Verdict) -> tuple[int, float]:
    """More grades, then later grades (compared as instants), decide which copy of a duplicated
    verdict wins."""
    stamps = [verdict.adjudicated_at] + [f.adjudicated_at for r in verdict.reviews for f in r.findings]
    stamps += [r.human_review.reviewed_at for r in verdict.reviews if r.human_review]
    graded = (sum(1 for r in verdict.reviews for f in r.findings if f.adjudication)
              + sum(1 for r in verdict.reviews if r.human_review) + bool(verdict.human_verdict))
    return graded, max((_when(s).timestamp() for s in stamps if s), default=float("-inf"))


def load(directories: list[Path]) -> Loaded:
    """Read every verdict and log line; skip what cannot be parsed and count it."""
    loaded = Loaded(directories=list(directories))
    by_run: dict[tuple[str, str], int] = {}
    seen_events: set[str] = set()
    for directory in directories:
        try:
            if not directory.is_dir():
                loaded.missing.append(str(directory))
                continue
            paths = []
            for entry in sorted(directory.iterdir()):
                if entry.suffix != ".json":
                    continue
                if entry.is_file():
                    paths.append(entry)
                else:
                    loaded.unreadable += 1
                    loaded.problems.append(f"{entry}: not a regular file")
        except OSError as exc:
            loaded.unreadable += 1
            loaded.problems.append(f"{directory}: directory not readable ({type(exc).__name__})")
            continue
        for path in paths:
            try:
                verdict = Verdict.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError) as exc:
                loaded.unreadable += 1
                loaded.problems.append(f"{path}: not a readable verdict ({type(exc).__name__})")
                continue
            key = (verdict.request_id, verdict.run_id)
            if key in by_run:
                loaded.duplicates += 1
                index = by_run[key]
                if _grading_progress(verdict) > _grading_progress(loaded.verdicts[index][1]):
                    loaded.verdicts[index] = (path, verdict)
                continue
            by_run[key] = len(loaded.verdicts)
            loaded.verdicts.append((path, verdict))
        log_path = directory / ADJUDICATION_LOG
        try:
            if not log_path.is_file():
                continue
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError) as exc:
            loaded.unreadable += 1
            loaded.problems.append(f"{log_path}: unreadable ({type(exc).__name__})")
            continue
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                loaded.unreadable += 1
                loaded.problems.append(f"{log_path}:{number}: not JSON; adjudicate cannot publish history "
                                       "in this directory until the line is repaired")
                continue
            if (not isinstance(event, dict) or not isinstance(event.get("event_id"), str)
                    or any(not isinstance(event.get(key), (str, type(None))) for key in EVENT_FIELDS)):
                loaded.unreadable += 1
                loaded.problems.append(f"{log_path}:{number}: not an adjudication event")
                continue
            if event["event_id"] in seen_events:
                loaded.duplicates += 1
                continue
            seen_events.add(event["event_id"])
            loaded.events.append(event)
    known = {verdict.run_id for _, verdict in loaded.verdicts}
    loaded.orphan_events = sum(1 for event in loaded.events if event.get("run_id") not in known)
    return loaded


def _directories(args: argparse.Namespace) -> list[Path]:
    return verdict_dirs(getattr(args, "dir", None))


def _skipped(loaded: Loaded) -> str | None:
    if not (loaded.unreadable or loaded.duplicates or loaded.orphan_events):
        return None
    return (f"Skipped {loaded.unreadable} unreadable and {loaded.duplicates} duplicate records; "
            f"{loaded.orphan_events} events refer to verdicts not read.")


def _report_problems(loaded: Loaded) -> None:
    """Name what was skipped on standard error, so the user can find and repair it."""
    for directory in loaded.missing:
        print(f"Not a directory: {directory}", file=sys.stderr)
    for problem in loaded.problems:
        print(f"Skipped {problem}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pending
# ---------------------------------------------------------------------------


def _vote(review: Review) -> str:
    return review.vote.value if hasattr(review.vote, "value") else str(review.vote)


def contested(verdict: Verdict, review: Review, finding: Finding) -> str | None:
    """Why grading this finding is informative: its reviewer disagreed with the outcome.

    The local reviewer-command guard turns verified into needs_revision without a vote, so a
    guarded verdict counts as verified here; an abstaining reviewer did not vote, so none of its
    findings is contested."""
    vote = _vote(review)
    if vote == "abstain":
        return None
    outcome = "verified" if verdict.local_guard_applied else verdict.status
    if outcome == "verified" and vote == "revise":
        return "voted revise; the panel verified"
    if finding.severity == "blocking" and outcome in ("needs_revision", "blocked") and verdict.up > verdict.down:
        return "blocking finding changed the outcome"
    if outcome in ("needs_revision", "blocked") and vote == "approve":
        return "voted approve; the panel revised"
    if outcome == "insufficient_jury" and verdict.up > 0 and verdict.down > 0:
        return "split vote, no verdict"
    return None


def _judge_ref(verdict: Verdict, review: Review) -> str:
    """A --judge value that `agentjury adjudicate` resolves to exactly this review."""
    if sum(1 for r in verdict.reviews if r.judge == review.judge) == 1:
        return review.judge
    return review.review_id


_SHELL_SAFE = re.compile(r"^[A-Za-z0-9_./:+=-]+\Z")
_SHELL_SAFE_NT = re.compile(r"^[A-Za-z0-9_./:+=\\-]+\Z")
# PowerShell also reads the typographic quotes U+2018..U+201E as quotes, and cmd.exe has no quoting
# at all, so a value carrying these (or cmd.exe metacharacters, on Windows) is never printed.
_NEVER_PRINT = re.compile(r"[\u2018-\u201e]")
_NEVER_PRINT_NT = re.compile(r'[\u2018-\u201e&|^%<>!"]')
FLAGS = {"--dir", "--judge", "--finding", "--producer-verdict", "--verdict"}
NO_COMMAND = "(no command printed: an identifier contains characters that cannot be quoted safely; use --json)"


def _shell(value: str) -> str:
    """One command argument as a shell reads it: bare when it needs no quoting, otherwise quoted
    for POSIX shells, or for PowerShell on Windows."""
    if os.name == "nt":
        return value if _SHELL_SAFE_NT.match(value) else "'" + value.replace("'", "''") + "'"
    return value if _SHELL_SAFE.match(value) else shlex.quote(value)


def _printable(part: str) -> bool:
    never = _NEVER_PRINT_NT if os.name == "nt" else _NEVER_PRINT
    return (escape_controls(part) == part and not never.search(part)
            and not (part.startswith("-") and part not in FLAGS))


def _command(*parts: str) -> str | None:
    """A pasteable `agentjury adjudicate` line, or None when a value cannot be printed as typed."""
    if not all(_printable(part) for part in parts):
        return None
    return "agentjury adjudicate " + " ".join(_shell(part) for part in parts)


def _command_line(command: str | None) -> str:
    return "    " + (command or NO_COMMAND)


def _when(value: datetime) -> datetime:
    """Naive timestamps count as UTC; an aware timestamp sorts without the platform's mktime."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _header(path: Path, verdict: Verdict, ref: str) -> dict[str, Any]:
    return {"run_id": verdict.run_id, "request_id": verdict.request_id, "directory": str(path.parent),
            "path": str(path), "ref": ref,
            "created_at": verdict.created_at, "status": verdict.status, "up": verdict.up, "down": verdict.down,
            "confidence": verdict.confidence, "task_type": verdict.task_type,
            "pending_events": len(verdict.pending_adjudication_events)}


def _band(confidence: float) -> str:
    return next(label for floor, label in CONFIDENCE_BANDS if confidence >= floor)


def _stratified(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first within each confidence band, bands interleaved from the highest down, so a
    bounded listing spreads producer grades across the confidence range calibration needs."""
    bands: dict[str, list[dict[str, Any]]] = {label: [] for _, label in CONFIDENCE_BANDS}
    for group in sorted(groups, key=lambda g: (-_when(g["created_at"]).timestamp(), g["run_id"])):
        bands[_band(group["confidence"])].append(group)
    ordered: list[dict[str, Any]] = []
    while any(bands.values()):
        for _, label in CONFIDENCE_BANDS:
            if bands[label]:
                ordered.append(bands[label].pop(0))
    return ordered


def pending(loaded: Loaded, *, only_contested: bool = False, task_type: str | None = None,
            status: str | None = None) -> dict[str, Any]:
    """Two queues: findings to grade (most informative first) and verdicts without a producer grade
    or a reviewer grade (spread across confidence bands). Filters narrow both queues."""
    findings_groups = []
    producer_groups = []
    stems: dict[Path, list[str]] = {}
    for path, _ in loaded.verdicts:
        stems.setdefault(path.parent, []).append(path.stem)
    for path, verdict in loaded.verdicts:
        # `agentjury adjudicate` finds a verdict by its run ID in the file name; a renamed file is
        # named by its path instead, so the printed command still resolves.
        by_id = verdict.run_id in path.stem and sum(1 for s in stems[path.parent] if verdict.run_id in s) == 1
        ref = verdict.run_id if by_id else str(path)
        if task_type is not None and (verdict.task_type or "(none)") != task_type:
            continue
        if status is not None and verdict.status != status:
            continue
        items = []
        for review in verdict.reviews:
            for number, finding in enumerate(review.findings, 1):
                if finding.adjudication is not None:
                    continue
                items.append({"judge": review.judge, "judge_ref": _judge_ref(verdict, review),
                              "review_id": review.review_id, "number": number, "finding_id": finding.id,
                              "severity": finding.severity, "text": finding.text,
                              "contested": contested(verdict, review, finding)})
        ungraded_reviews = [{"judge": r.judge, "judge_ref": _judge_ref(verdict, r)}
                            for r in verdict.reviews if r.human_review is None]
        if only_contested:
            items = [i for i in items if i["contested"]]
        if items:
            findings_groups.append({**_header(path, verdict, ref), "findings": items,
                                    "contested": any(i["contested"] for i in items),
                                    "severity_rank": min(SEVERITY_RANK.get(i["severity"], 3) for i in items)})
        needs_producer_grade = verdict.human_verdict is None
        if needs_producer_grade or ungraded_reviews:
            producer_groups.append({**_header(path, verdict, ref), "band": _band(verdict.confidence),
                                    "needs_producer_grade": needs_producer_grade,
                                    "reviews_without_grade": ungraded_reviews})
    findings_groups.sort(key=lambda g: (0 if g["contested"] else 1, g["severity_rank"],
                                        -_when(g["created_at"]).timestamp(), g["run_id"]))
    for group in findings_groups:
        del group["severity_rank"]
    producer_groups = _stratified(producer_groups)
    return {
        "counts": {
            "ungraded_findings": sum(len(g["findings"]) for g in findings_groups),
            "contested_findings": sum(1 for g in findings_groups for i in g["findings"] if i["contested"]),
            "verdicts_with_ungraded_findings": len(findings_groups),
            "verdicts_without_producer_grade": sum(1 for g in producer_groups if g["needs_producer_grade"]),
            "reviews_without_grade": sum(len(g["reviews_without_grade"]) for g in producer_groups),
        },
        # The counts above are the whole backlog even when --contested hides the second queue.
        "findings": findings_groups, "producer": [] if only_contested else producer_groups,
    }


def _group_line(group: dict[str, Any], flag: str = "") -> str:
    task_type = f"  {escape_controls(group['task_type'])}" if group["task_type"] else ""
    return (f"run {escape_controls(group['run_id'])}  req {escape_controls(group['request_id'])}  "
            f"{group['created_at']:%Y-%m-%d %H:%M}  "
            f"{group['status']}  ▲{group['up']} ▼{group['down']}  confidence {group['confidence']:.0%}"
            f"{task_type}{flag}")


def _events_note(group: dict[str, Any]) -> list[str]:
    if not group["pending_events"]:
        return []
    return [f"  ({group['pending_events']} adjudication events not yet in {ADJUDICATION_LOG}; "
            "any adjudicate on this verdict publishes them)"]


def pending_lines(result: dict[str, Any], loaded: Loaded, limit: int | None) -> list[str]:
    c = result["counts"]
    lines = [f"Pending adjudication: {c['ungraded_findings']} ungraded findings ({c['contested_findings']} contested) "
             f"in {c['verdicts_with_ungraded_findings']} verdicts; {c['verdicts_without_producer_grade']} verdicts "
             f"without a producer grade; {c['reviews_without_grade']} reviews without an overall grade. "
             "These totals are the backlog; grade what the listing puts first."]
    if _skipped(loaded):
        lines.append(_skipped(loaded))
    if not result["findings"] and not result["producer"]:
        return lines + ["Nothing pending."]
    lines.append(LEGEND)

    if result["findings"]:
        lines += ["", "Findings to grade, most informative first. N is the finding's position as saved, "
                      "the same number review, change status and Hermes /jury print."]
    shown = result["findings"][:limit] if limit is not None else result["findings"]
    for group in shown:
        lines += ["", _group_line(group, "  [contested]" if group["contested"] else ""), *_events_note(group)]
        for item in group["findings"]:
            why = f"  ({item['contested']})" if item["contested"] else ""
            lines.append(f"  {escape_controls(item['judge'])}  finding {item['number']}  [{item['severity']}]  "
                         f"{escape_controls(item['text'])}{why}")
            lines.append(_command_line(_command(group["ref"], "--dir", group["directory"], "--judge",
                                                item["judge_ref"], "--finding", str(item["number"]), "LABEL")))
    if len(shown) < len(result["findings"]):
        lines += ["", f"{len(result['findings']) - len(shown)} more verdicts with ungraded findings not shown; "
                      "raise -n to see them."]

    if result["producer"]:
        lines += ["", "Verdicts without a producer grade or a reviewer grade, spread across confidence bands and "
                      "newest first within each, so grades of the output itself cover the whole range the "
                      "confidence index spans."]
    shown = result["producer"][:limit] if limit is not None else result["producer"]
    for group in shown:
        lines += ["", _group_line(group, f"  [band {group['band']}]"), *_events_note(group)]
        if group["needs_producer_grade"]:
            lines.append(_command_line(_command(group["ref"], "--dir", group["directory"],
                                                "--producer-verdict", "GRADE")))
        if group["reviews_without_grade"]:
            names = ", ".join(escape_controls(r["judge"]) for r in group["reviews_without_grade"])
            lines.append(f"  reviews without an overall grade: {names}")
            lines.append(_command_line(_command(group["ref"], "--dir", group["directory"], "--judge",
                                                group["reviews_without_grade"][0]["judge_ref"], "--verdict", "VIEW")))
    if len(shown) < len(result["producer"]):
        lines += ["", f"{len(result['producer']) - len(shown)} more verdicts without a producer or reviewer grade "
                      "not shown; raise -n to see them."]
    return lines


def cmd_pending(args: argparse.Namespace) -> int:
    loaded = load(_directories(args))
    _report_problems(loaded)
    result = pending(loaded, only_contested=args.contested, task_type=args.task_type, status=args.status)
    if args.json:
        limit = args.n
        payload = {"directories": [str(d) for d in loaded.directories], "missing_directories": loaded.missing,
                   "problems": loaded.problems, "unreadable": loaded.unreadable,
                   "duplicates": loaded.duplicates, "orphan_events": loaded.orphan_events, **result}
        if limit is not None:
            payload["findings"] = result["findings"][:limit]
            payload["producer"] = result["producer"][:limit]
        print(json.dumps(payload, indent=2, default=_json_default, ensure_ascii=True))
        return 0
    print("\n".join(pending_lines(result, loaded, args.n)))
    return 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _param_value(key: str, value: Any) -> Any:
    shape = PARAM_SHAPES[key]
    if isinstance(shape, tuple):
        if not isinstance(value, shape) or isinstance(value, bool):
            return None
        if isinstance(value, int):  # keep integers every JSON reader represents exactly
            return value if abs(value) < 2**53 else None
        return value if math.isfinite(value) else None
    return value if isinstance(value, str) and shape.match(value) else None


def export_params(params: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Allowlisted keys whose values have the expected shape, and the number of entries dropped."""
    kept = {}
    for key in PARAM_SHAPES:
        if key in params:
            value = _param_value(key, params[key])
            if value is not None:
                kept[key] = value
    return kept, len(params) - len(kept)


def export_error(error: str) -> dict[str, Any]:
    """The failed reviewer's name and exception class from the panel's `name: Class: message` layout;
    an error string in any other layout exports as nulls, so no message token can leave."""
    judge, first, rest = error.partition(": ")
    klass, second, _message = rest.partition(": ")
    if first and second and _NAME.match(judge) and _IDENT.match(klass):
        return {"judge": judge, "error": klass}
    return {"judge": None, "error": None}


class _Ids:
    """Identity strings off the expected shape are replaced by a stable digest, never refused."""

    def __init__(self) -> None:
        self.pseudonymised = 0

    def __call__(self, value: str | None) -> str | None:
        if value is None or _ID.match(value):
            return value
        self.pseudonymised += 1
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def export_finding(finding: Finding, ids: _Ids) -> dict[str, Any]:
    evidence = finding.evidence
    return {"id": ids(finding.id), "severity": finding.severity, "has_evidence": evidence is not None,
            "basis_source": evidence.basis_source if evidence is not None else None,
            "adjudication": finding.adjudication, "adjudicated_at": finding.adjudicated_at}


def export_review(review: Review, ids: _Ids) -> tuple[dict[str, Any], int]:
    human = review.human_review
    params, dropped = export_params(review.params)
    return {
        "review_id": ids(review.review_id), "config_id": ids(review.config_id), "judge": review.judge,
        "role": review.role,
        "provider": review.provider, "model": review.model, "observed_model": review.observed_model,
        "vote": _vote(review), "score": review.score, "self_confidence": review.self_confidence,
        "rubric_version": review.rubric_version, "prompt_hash": ids(review.prompt_hash), "params": params,
        "latency_ms": review.latency_ms, "tokens_in": review.tokens_in, "tokens_out": review.tokens_out,
        "created_at": review.created_at,
        "human_review": None if human is None else {"verdict": human.verdict, "reviewed_at": human.reviewed_at},
        "findings": [export_finding(f, ids) for f in review.findings],
    }, dropped


def export_verdict(verdict: Verdict, ids: _Ids) -> tuple[dict[str, Any], int]:
    """Only identities, numbers, labels and timestamps: nothing that was reviewed."""
    reviews = [export_review(r, ids) for r in verdict.reviews]
    return {
        "run_id": ids(verdict.run_id), "request_id": ids(verdict.request_id), "panel_id": ids(verdict.panel_id),
        "schema_version": verdict.schema_version, "created_at": verdict.created_at,
        "task_type": verdict.task_type, "domain": verdict.domain,
        "producer": {"framework": verdict.producer.framework, "provider": verdict.producer.provider,
                     "model": verdict.producer.model},
        "requested": verdict.requested, "responded": verdict.responded, "abstained": verdict.abstained,
        "quorum": verdict.quorum, "up": verdict.up, "down": verdict.down, "score": verdict.score,
        "consensus": verdict.consensus, "diversity": verdict.diversity, "confidence": verdict.confidence,
        "status": verdict.status, "local_signal_rules": [s.rule_id for s in verdict.local_signals],
        "local_guard_applied": verdict.local_guard_applied,
        "errors": [export_error(e) for e in verdict.errors], "error_count": len(verdict.errors),
        "artifact_coverage": dict(Counter(c.coverage for c in verdict.artifact_coverage)),
        "pending_event_count": len(verdict.pending_adjudication_events),
        "human_verdict": verdict.human_verdict, "adjudicated_at": verdict.adjudicated_at,
        "reviews": [r for r, _ in reviews],
    }, sum(d for _, d in reviews)


def export_event(event: dict[str, Any], ids: _Ids) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, shape in STRING_PATHS.items():
        if len(path) != 3 or path[0] != "events":
            continue
        key = path[2]
        value = event.get(key)
        if isinstance(value, str) and shape is _ID:
            out[key] = ids(value)
        elif isinstance(value, str) and _matches(shape, value):
            out[key] = value
        else:
            out[key] = None
    return out


def _matches(shape: Any, value: str) -> bool:
    if shape == FREE:
        return True
    if isinstance(shape, set):
        return value in shape
    return bool(shape.match(value))


def build_export(loaded: Loaded, exported_at: datetime | None = None) -> dict[str, Any]:
    ids = _Ids()
    exported = [export_verdict(v, ids) for _, v in loaded.verdicts]
    events = [export_event(e, ids) for e in loaded.events]
    verdicts = [v for v, _ in exported]
    reviews = [r for v in verdicts for r in v["reviews"]]
    findings = [f for r in reviews for f in r["findings"]]
    return {
        "kind": EXPORT_KIND, "version": EXPORT_VERSION, "agentjury_version": __version__,
        "exported_at": exported_at or datetime.now(timezone.utc),
        "counts": {
            "verdicts": len(verdicts), "reviews": len(reviews), "findings": len(findings),
            "graded_findings": sum(1 for f in findings if f["adjudication"] is not None),
            "graded_reviews": sum(1 for r in reviews if r["human_review"] is not None),
            "producer_grades": sum(1 for v in verdicts if v["human_verdict"] is not None),
            "events": len(loaded.events), "orphan_events": loaded.orphan_events,
            "pending_events": sum(v["pending_event_count"] for v in verdicts),
            "params_dropped": sum(d for _, d in exported), "ids_pseudonymised": ids.pseudonymised,
            "unreadable": loaded.unreadable, "duplicates": loaded.duplicates,
        },
        "verdicts": verdicts,
        "events": events,
    }


def _walk(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, path + (str(key),))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, path + ("*",))
    elif isinstance(value, str):
        yield path, value


def audit_export(document: dict[str, Any]) -> list[str]:
    """Paths of strings an export must not contain: anything outside the allowlist or off its shape."""
    bad = []
    for path, value in _walk(document):
        shape = STRING_PATHS.get(path)
        if shape is None or not _matches(shape, value):
            bad.append("/".join(path))
    return sorted(set(bad))


def free_text_values(document: dict[str, Any]) -> dict[str, list[str]]:
    """The operator-chosen labels an export carries, for review before sharing."""
    values: dict[str, set[str]] = {}
    for path, value in _walk(document):
        if STRING_PATHS.get(path) == FREE:
            values.setdefault(path[-1], set()).add(value)
    return {key: sorted(items) for key, items in sorted(values.items())}


def export_summary(document: dict[str, Any]) -> list[str]:
    c = document["counts"]
    lines = [f"Exported {c['verdicts']} verdicts, {c['reviews']} reviews, {c['findings']} findings "
             f"({c['graded_findings']} graded), {c['graded_reviews']} review grades, {c['producer_grades']} producer "
             f"grades and {c['events']} events ({c['orphan_events']} for verdicts not read).",
             f"Counted only: {c['pending_events']} unpublished events, {c['params_dropped']} reviewer parameters "
             f"outside the allowlist, {c['ids_pseudonymised']} identifier occurrences replaced by digests, "
             f"{c['unreadable']} unreadable and {c['duplicates']} duplicate records.",
             "No reviewed text, excerpts, reasons, notes, error messages, adjudicator names or file paths are included."]
    labels = free_text_values(document)
    if labels:
        lines.append("Operator-chosen labels that leave with the export; check them before sharing:")
        lines += [f"  {key}: " + ", ".join(escape_controls(v) for v in items) for key, items in labels.items()]
    return lines


def cmd_export(args: argparse.Namespace) -> int:
    loaded = load(_directories(args))
    _report_problems(loaded)
    document = build_export(loaded)
    try:
        serialised = json.loads(json.dumps(document, default=_json_default, allow_nan=False))
    except ValueError:
        print("Export refused: a number in the verdicts is not finite.", file=sys.stderr)
        return EXIT_INVALID
    offending = audit_export(serialised)
    if offending:
        print("Export refused: a value outside the allowlist was found at "
              + ", ".join(escape_controls(p) for p in offending[:10]), file=sys.stderr)
        return EXIT_INVALID
    text = json.dumps(serialised, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    if args.out:
        try:
            atomic_write(Path(args.out), text)
        except OSError as exc:
            print(f"Could not write {args.out}: {type(exc).__name__}", file=sys.stderr)
            return EXIT_INVALID
        print("\n".join([*export_summary(document), f"Written to {args.out}"]))
    else:
        sys.stdout.write(text)
        print("\n".join(export_summary(document)), file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _bucket() -> dict[str, int]:
    return {"findings": 0, "graded": 0, "correct": 0, "partially_correct": 0, "wrong": 0,
            "reviews": 0, "abstained": 0, "reviews_graded": 0, "agree": 0, "partial": 0, "disagree": 0,
            "on_graded_outputs": 0, "false_approvals": 0, "false_rejections": 0, "agreements": 0}


def _add_review(bucket: dict[str, int], review: dict[str, Any], human_verdict: str | None) -> None:
    bucket["reviews"] += 1
    vote = review.get("vote")
    if vote == "abstain":
        bucket["abstained"] += 1
    human = review.get("human_review")
    if human and human.get("verdict") in ("agree", "partial", "disagree"):
        bucket["reviews_graded"] += 1
        bucket[human["verdict"]] += 1
    for finding in review.get("findings", []):
        bucket["findings"] += 1
        grade = finding.get("adjudication")
        if grade in ("correct", "partially_correct", "wrong"):
            bucket["graded"] += 1
            bucket[grade] += 1
    # Abstentions are not votes, so they appear in neither error count, as in benchmark-audit.
    if human_verdict in ("correct", "flawed") and vote in ("approve", "revise"):
        bucket["on_graded_outputs"] += 1
        if vote == "approve" and human_verdict == "flawed":
            bucket["false_approvals"] += 1
        elif vote == "revise" and human_verdict == "correct":
            bucket["false_rejections"] += 1
        else:
            bucket["agreements"] += 1


def _shown_params(params: dict[str, Any]) -> dict[str, Any]:
    """The parameters the stats listing shows, each kept only in its allowlisted shape."""
    shown = {}
    for key in ("timeout", "effort", "thinking", "max_tokens"):
        value = _param_value(key, params[key]) if key in params else None
        if value is not None:
            shown[key] = value
    return shown


def stats(document: dict[str, Any]) -> dict[str, Any]:
    """Descriptive counts per reviewer configuration and task type from an export document."""
    configs: dict[str, dict[str, Any]] = {}
    jury = {"graded": 0, "unsafe_approvals": 0, "false_rejections": 0, "agreements": 0, "unavailable": 0,
            "local_interventions": 0}
    pairs: Counter = Counter()
    verdicts = document.get("verdicts") or []
    graded_findings = 0
    for verdict in verdicts:
        human = verdict.get("human_verdict")
        status = verdict.get("status")
        if human in ("correct", "flawed"):
            jury["graded"] += 1
            pairs[f"{status} with {human}"] += 1
            if status == "insufficient_jury":
                jury["unavailable"] += 1
            elif status == "verified" and human == "flawed":
                jury["unsafe_approvals"] += 1
            elif status in ("needs_revision", "blocked") and human == "correct":
                jury["false_rejections"] += 1
            else:
                jury["agreements"] += 1
            if verdict.get("local_guard_applied"):
                jury["local_interventions"] += 1
        task_type = verdict.get("task_type") or "(none)"
        for review in verdict.get("reviews") or []:
            config_id = review.get("config_id") or "(unknown)"
            params = review.get("params") or {}
            graded_findings += sum(1 for f in review.get("findings") or []
                                   if f.get("adjudication") in ("correct", "partially_correct", "wrong"))
            entry = configs.setdefault(config_id, {
                "config_id": config_id, "judge": review.get("judge"), "role": review.get("role"),
                "provider": review.get("provider"), "model": review.get("model"),
                "rubric_version": review.get("rubric_version"), "prompt_hash": review.get("prompt_hash"),
                "params": _shown_params(params),
                "all": _bucket(), "task_types": {},
            })
            _add_review(entry["all"], review, human)
            _add_review(entry["task_types"].setdefault(task_type, _bucket()), review, human)
    return {
        "descriptive_only": True,
        "verdicts": len(verdicts),
        "producer_grades": jury["graded"],
        "graded_findings": graded_findings,
        "jury_vs_producer_grade": jury,
        "status_with_producer_grade": dict(sorted(pairs.items())),
        "configurations": sorted(configs.values(), key=lambda c: (-c["all"]["graded"], c["judge"] or "")),
    }


DISCLAIMER = ("These are descriptive counts of human grades, not reputation weights or calibrated "
              "probabilities. Nothing in AgentJury reads them to change a verdict.")


def _bucket_text(bucket: dict[str, int]) -> str:
    return (f"findings {bucket['findings']} (graded {bucket['graded']}: correct {bucket['correct']}, "
            f"partially_correct {bucket['partially_correct']}, wrong {bucket['wrong']}); "
            f"reviews {bucket['reviews']} ({bucket['abstained']} abstained; graded {bucket['reviews_graded']}: "
            f"agree {bucket['agree']}, partial {bucket['partial']}, disagree {bucket['disagree']}); "
            f"on {bucket['on_graded_outputs']} graded outputs: false approvals {bucket['false_approvals']}, "
            f"false rejections {bucket['false_rejections']}, agreements {bucket['agreements']}")


def stats_lines(result: dict[str, Any]) -> list[str]:
    lines = [f"Adjudication stats: {result['graded_findings']} graded findings in {result['verdicts']} verdicts "
             f"({result['producer_grades']} with a producer grade).", DISCLAIMER, "",
             "Reviewer configurations, each counted on its own even when it shares a model; "
             "a different prompt, parameter or rubric is a different configuration."]
    if not result["configurations"]:
        lines.append("  No reviews found.")
    safe = lambda value: escape_controls(str(value))  # noqa: E731 - every label may come from a received file
    for config in result["configurations"]:
        params = ", ".join(f"{safe(k)} {safe(v)}" for k, v in config["params"].items())
        lines.append(f"  {safe(config['judge'])}  {safe(config['model'])}  rubric {safe(config['rubric_version'])}  "
                     f"prompt {safe(config['prompt_hash'])}  config {safe(config['config_id'])}"
                     + (f"  ({params})" if params else ""))
        lines.append(f"    all task types: {_bucket_text(config['all'])}")
        for task_type, bucket in sorted(config["task_types"].items()):
            lines.append(f"    {escape_controls(task_type)}: {_bucket_text(bucket)}")
    jury = result["jury_vs_producer_grade"]
    lines += ["", f"Jury status against producer grade, on {jury['graded']} graded verdicts: unsafe approvals "
                  f"{jury['unsafe_approvals']}, false rejections {jury['false_rejections']}, agreements "
                  f"{jury['agreements']}, unavailable {jury['unavailable']}, local interventions "
                  f"{jury['local_interventions']}."]
    if result["status_with_producer_grade"]:
        lines.append("  " + ", ".join(f"{escape_controls(key)} {count}"
                                      for key, count in result["status_with_producer_grade"].items()))
    return lines


def _well_formed(document: Any) -> str | None:
    """Why a received document is not an export that stats can count, or None when it is."""
    if (not isinstance(document, dict) or document.get("kind") != EXPORT_KIND
            or document.get("version") != EXPORT_VERSION):
        return "Not an AgentJury adjudication export of a supported version."
    text = (str, type(None))
    verdicts = document.get("verdicts", [])
    if not isinstance(verdicts, list) or not isinstance(document.get("counts", {}), dict):
        return "Not a well-formed export: verdicts or counts have the wrong type."
    for verdict in verdicts:
        reviews = verdict.get("reviews", []) if isinstance(verdict, dict) else None
        if not isinstance(reviews, list) or not all(isinstance(verdict.get(key), text)
                                                    for key in ("human_verdict", "status", "task_type")):
            return "Not a well-formed export: a verdict has the wrong shape."
        for review in reviews:
            findings = review.get("findings", []) if isinstance(review, dict) else None
            human = review.get("human_review") if isinstance(review, dict) else None
            if (not isinstance(findings, list) or not isinstance(review.get("params", {}), (dict, type(None)))
                    or not isinstance(human, (dict, type(None)))
                    or (human is not None and not isinstance(human.get("verdict"), text))
                    or not all(isinstance(review.get(key), text) for key in
                               ("config_id", "judge", "role", "provider", "model", "rubric_version",
                                "prompt_hash", "vote"))
                    or not all(isinstance(f, dict) and isinstance(f.get("adjudication"), text) for f in findings)):
                return "Not a well-formed export: a review has the wrong shape."
    offending = audit_export(document)
    if offending:
        return ("Not a well-formed export: unexpected value at "
                + ", ".join(escape_controls(p) for p in offending[:10]))
    return None


def _render_stats(result: dict[str, Any], as_json: bool) -> str:
    if as_json:
        return json.dumps({**result, "disclaimer": DISCLAIMER}, indent=2, ensure_ascii=True, allow_nan=False)
    return "\n".join(stats_lines(result))


def cmd_stats(args: argparse.Namespace) -> int:
    if args.source:
        try:
            text = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
            document = json.loads(text)
        except (OSError, ValueError, RecursionError):
            print("Cannot read the export file as JSON.", file=sys.stderr)
            return EXIT_INVALID
        problem = _well_formed(document)
        if problem:
            print(problem, file=sys.stderr)
            return EXIT_INVALID
        try:
            rendered = _render_stats(stats(document), args.json)
        except (TypeError, AttributeError, KeyError, ValueError):
            print("Not a well-formed AgentJury adjudication export.", file=sys.stderr)
            return EXIT_INVALID
    else:
        loaded = load(_directories(args))
        _report_problems(loaded)
        document = json.loads(json.dumps(build_export(loaded), default=_json_default))
        rendered = _render_stats(stats(document), args.json)
    print(rendered)
    return 0


def _count(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def add_parser(sub: argparse._SubParsersAction) -> None:
    group = sub.add_parser("adjudication", help="What needs grading, a text-free export of grades, and descriptive counts.")
    commands = group.add_subparsers(dest="adjudication_command", required=True)
    directory_help = "Verdict directory; repeatable (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts)."

    p = commands.add_parser("pending", help="List ungraded findings, most informative first, with the grading commands.")
    p.add_argument("--dir", action="append", help=directory_help)
    p.add_argument("-n", type=_count, default=20, help="Verdicts to show per section (default: 20).")
    p.add_argument("--contested", action="store_true", help="Only findings whose reviewer disagreed with the outcome.")
    p.add_argument("--task-type", help="Only verdicts with this task type ((none) for untyped).")
    p.add_argument("--status", choices=["verified", "needs_revision", "blocked", "insufficient_jury"],
                   help="Only verdicts with this status.")
    p.add_argument("--json", action="store_true", help="Print structured data.")
    p.set_defaults(func=cmd_pending)

    e = commands.add_parser("export", help="Write grades and reviewer identities as JSON, with no reviewed text.")
    e.add_argument("--dir", action="append", help=directory_help)
    e.add_argument("--out", help="File to write (default: standard output, summary on standard error).")
    e.set_defaults(func=cmd_export)

    s = commands.add_parser("stats", help="Descriptive counts of grades per reviewer configuration and task type.")
    where = s.add_mutually_exclusive_group()
    where.add_argument("--dir", action="append", help=directory_help)
    where.add_argument("--from", dest="source", metavar="EXPORT",
                       help="Read an export file (- for standard input) instead of verdict directories.")
    s.add_argument("--json", action="store_true", help="Print structured data.")
    s.set_defaults(func=cmd_stats)
