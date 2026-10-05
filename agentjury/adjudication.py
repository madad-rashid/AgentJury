"""
Human grading support: what still needs a grade, a text-free export of the
grades that exist, and descriptive counts of them.

    agentjury adjudication pending [--dir DIR]... [-n N] [--json]
    agentjury adjudication export  [--dir DIR]... [--out FILE]
    agentjury adjudication stats   [--dir DIR]... | --from EXPORT [--json]

These commands read saved verdicts and the adjudication log, contact nothing,
and modify nothing. Nothing here weights a vote or changes a verdict: the
counts are descriptive, not reputation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .cli import ADJUDICATION_LOG
from .local_store import atomic_write, verdict_dir
from .protocol import Finding, Review, Verdict
from .reviewer_guard import escape_controls

EXPORT_KIND = "agentjury.adjudication.export"
EXPORT_VERSION = 1
# Reviewer parameters known not to carry secrets, text or endpoints in clear.
PARAM_KEYS = ("route", "transport", "format", "endpoint_hash", "requested_model",
              "completion_policy", "timeout", "max_tokens", "effort", "thinking")
EVENT_KEYS = ("event_id", "at", "kind", "run_id", "request_id", "review_id", "config_id",
              "judge", "finding_id", "old", "new")
SEVERITY_RANK = {"blocking": 0, "major": 1, "minor": 2}
LABELS = "correct|partially_correct|wrong"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass
class Loaded:
    """Verdicts and adjudication events from one or more verdict directories."""

    verdicts: list[tuple[Path, Verdict]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    unreadable: int = 0
    duplicates: int = 0


def load(directories: list[Path]) -> Loaded:
    """Read every verdict and log line; skip what cannot be parsed and count it."""
    loaded = Loaded(directories=list(directories))
    seen_runs: set[tuple[str, str]] = set()
    seen_events: set[str] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                verdict = Verdict.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded.unreadable += 1
                continue
            key = (verdict.request_id, verdict.run_id)
            if key in seen_runs:
                loaded.duplicates += 1
                continue
            seen_runs.add(key)
            loaded.verdicts.append((path, verdict))
        log_path = directory / ADJUDICATION_LOG
        if not log_path.is_file():
            continue
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            loaded.unreadable += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                loaded.unreadable += 1
                continue
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
                loaded.unreadable += 1
                continue
            if event["event_id"] in seen_events:
                loaded.duplicates += 1
                continue
            seen_events.add(event["event_id"])
            loaded.events.append(event)
    return loaded


def _directories(args: argparse.Namespace) -> list[Path]:
    given = [Path(d) for d in (getattr(args, "dir", None) or [])]
    return given or [verdict_dir(None)]


# ---------------------------------------------------------------------------
# Pending
# ---------------------------------------------------------------------------


def contested(verdict: Verdict, finding: Finding) -> str | None:
    """Why a finding carries information: split vote, overruled by the panel, or decisive."""
    if verdict.status == "verified" and finding.severity in ("major", "blocking"):
        return "panel overruled this reviewer"
    if verdict.status in ("needs_revision", "blocked") and finding.severity == "blocking":
        return "decided the outcome"
    if verdict.up > 0 and verdict.down > 0:
        return "split vote"
    return None


def _judge_ref(verdict: Verdict, review: Review) -> str:
    """A --judge value `agentjury adjudicate` resolves to exactly this review."""
    if sum(1 for r in verdict.reviews if r.judge == review.judge) == 1:
        return review.judge
    return review.review_id


def pending(loaded: Loaded) -> list[dict[str, Any]]:
    """Verdicts with ungraded findings or no producer grade, most informative first."""
    groups = []
    for path, verdict in loaded.verdicts:
        findings = []
        for review in verdict.reviews:
            for number, finding in enumerate(review.findings, 1):
                if finding.adjudication is not None:
                    continue
                reason = contested(verdict, finding)
                findings.append({
                    "judge": review.judge, "judge_ref": _judge_ref(verdict, review), "review_id": review.review_id,
                    "finding_id": finding.id,
                    "number": number, "severity": finding.severity, "text": finding.text,
                    "contested": reason, "rank": (0 if reason else 1, SEVERITY_RANK.get(finding.severity, 3)),
                })
        producer_missing = verdict.human_verdict is None
        if not findings and not producer_missing:
            continue
        findings.sort(key=lambda f: f["rank"])
        for item in findings:
            del item["rank"]
        groups.append({
            "run_id": verdict.run_id, "request_id": verdict.request_id, "directory": str(path.parent),
            "created_at": verdict.created_at, "status": verdict.status, "up": verdict.up, "down": verdict.down,
            "task_type": verdict.task_type, "findings": findings, "producer_missing": producer_missing,
            "contested": any(f["contested"] for f in findings),
            "severity_rank": min((SEVERITY_RANK.get(f["severity"], 3) for f in findings), default=3),
        })
    groups.sort(key=lambda g: (0 if g["contested"] else 1, g["severity_rank"], -g["created_at"].timestamp()))
    for group in groups:
        del group["severity_rank"]
    return groups


def pending_lines(groups: list[dict[str, Any]], loaded: Loaded, limit: int | None) -> list[str]:
    findings_total = sum(len(g["findings"]) for g in groups)
    contested_total = sum(1 for g in groups for f in g["findings"] if f["contested"])
    producer_missing = sum(1 for g in groups if g["producer_missing"])
    lines = [f"Pending adjudication: {findings_total} ungraded findings ({contested_total} contested) in "
             f"{len(groups)} verdicts; {producer_missing} verdicts without a producer grade."]
    if loaded.unreadable or loaded.duplicates:
        lines.append(f"Skipped {loaded.unreadable} unreadable and {loaded.duplicates} duplicate records.")
    shown = groups if limit is None else groups[:limit]
    for group in shown:
        flag = "  [contested]" if group["contested"] else ""
        task_type = f"  {escape_controls(group['task_type'])}" if group["task_type"] else ""
        lines += ["", f"run {group['run_id']}  req {group['request_id']}  {group['created_at']:%Y-%m-%d %H:%M}  "
                      f"{group['status']}  ▲{group['up']} ▼{group['down']}{task_type}{flag}"]
        folder = group["directory"]
        quoted = f'"{folder}"' if any(ch.isspace() for ch in folder) else folder
        for item in group["findings"]:
            why = f"  ({item['contested']})" if item["contested"] else ""
            lines.append(f"  {escape_controls(item['judge'])}  finding {item['number']}  [{item['severity']}]  "
                         f"{escape_controls(item['text'])}{why}")
            lines.append(f"    agentjury adjudicate {group['run_id']} --dir {quoted} --judge "
                         f"{escape_controls(item['judge_ref'])} --finding {item['number']} {LABELS}")
        if group["producer_missing"]:
            lines.append("  producer grade missing:")
            lines.append(f"    agentjury adjudicate {group['run_id']} --dir {quoted} --producer-verdict correct|flawed")
    if len(shown) < len(groups):
        lines += ["", f"{len(groups) - len(shown)} more verdicts not shown; raise -n to see them."]
    if not groups:
        lines.append("Nothing pending.")
    return lines


def cmd_pending(args: argparse.Namespace) -> int:
    loaded = load(_directories(args))
    groups = pending(loaded)
    if args.json:
        payload = {"directories": [str(d) for d in loaded.directories], "unreadable": loaded.unreadable,
                   "duplicates": loaded.duplicates, "verdicts": groups if args.n is None else groups[:args.n],
                   "pending_verdicts": len(groups)}
        print(json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False))
        return 0
    print("\n".join(pending_lines(groups, loaded, args.n)))
    return 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def export_finding(finding: Finding) -> dict[str, Any]:
    evidence = finding.evidence
    return {"id": finding.id, "severity": finding.severity, "has_evidence": evidence is not None,
            "basis_source": evidence.basis_source if evidence is not None else None,
            "adjudication": finding.adjudication, "adjudicated_at": finding.adjudicated_at}


def export_review(review: Review) -> dict[str, Any]:
    human = review.human_review
    return {
        "review_id": review.review_id, "config_id": review.config_id, "judge": review.judge, "role": review.role,
        "provider": review.provider, "model": review.model, "observed_model": review.observed_model,
        "vote": review.vote.value if hasattr(review.vote, "value") else review.vote, "score": review.score,
        "self_confidence": review.self_confidence, "rubric_version": review.rubric_version,
        "prompt_hash": review.prompt_hash,
        "params": {key: review.params[key] for key in PARAM_KEYS
                   if key in review.params and isinstance(review.params[key], (str, int, float, bool))},
        "latency_ms": review.latency_ms, "tokens_in": review.tokens_in, "tokens_out": review.tokens_out,
        "created_at": review.created_at,
        "human_review": None if human is None else {"verdict": human.verdict, "reviewed_at": human.reviewed_at},
        "findings": [export_finding(f) for f in review.findings],
    }


def export_verdict(verdict: Verdict) -> dict[str, Any]:
    """Only identities, numbers, labels and timestamps: nothing that was reviewed."""
    return {
        "run_id": verdict.run_id, "request_id": verdict.request_id, "panel_id": verdict.panel_id,
        "schema_version": verdict.schema_version, "created_at": verdict.created_at,
        "task_type": verdict.task_type, "domain": verdict.domain,
        "producer": {"framework": verdict.producer.framework, "provider": verdict.producer.provider,
                     "model": verdict.producer.model},
        "requested": verdict.requested, "responded": verdict.responded, "abstained": verdict.abstained,
        "quorum": verdict.quorum, "up": verdict.up, "down": verdict.down, "score": verdict.score,
        "consensus": verdict.consensus, "diversity": verdict.diversity, "confidence": verdict.confidence,
        "status": verdict.status, "local_signal_rules": [s.rule_id for s in verdict.local_signals],
        "local_guard_applied": verdict.local_guard_applied, "error_count": len(verdict.errors),
        "artifact_coverage": dict(Counter(c.coverage for c in verdict.artifact_coverage)),
        "pending_event_count": len(verdict.pending_adjudication_events),
        "human_verdict": verdict.human_verdict, "adjudicated_at": verdict.adjudicated_at,
        "reviews": [export_review(r) for r in verdict.reviews],
    }


def export_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: event.get(key) for key in EVENT_KEYS
            if isinstance(event.get(key), (str, int, float, bool)) or event.get(key) is None}


def build_export(loaded: Loaded, exported_at: datetime | None = None) -> dict[str, Any]:
    verdicts = [export_verdict(v) for _, v in loaded.verdicts]
    reviews = [r for v in verdicts for r in v["reviews"]]
    findings = [f for r in reviews for f in r["findings"]]
    return {
        "kind": EXPORT_KIND, "version": EXPORT_VERSION, "agentjury_version": __version__,
        "exported_at": exported_at or datetime.now(timezone.utc),
        "counts": {
            "verdicts": len(verdicts), "reviews": len(reviews), "findings": len(findings),
            "graded_findings": sum(1 for f in findings if f["adjudication"] is not None),
            "producer_grades": sum(1 for v in verdicts if v["human_verdict"] is not None),
            "events": len(loaded.events),
            "pending_events": sum(v["pending_event_count"] for v in verdicts),
            "unreadable": loaded.unreadable, "duplicates": loaded.duplicates,
        },
        "verdicts": verdicts,
        "events": [export_event(e) for e in loaded.events],
    }


def export_summary(document: dict[str, Any]) -> str:
    c = document["counts"]
    return (f"Exported {c['verdicts']} verdicts, {c['reviews']} reviews, {c['findings']} findings "
            f"({c['graded_findings']} graded), {c['producer_grades']} producer grades and {c['events']} events; "
            f"{c['pending_events']} unpublished events counted only; "
            f"{c['unreadable']} unreadable and {c['duplicates']} duplicate records skipped. "
            "No reviewed text, excerpts, notes, names or paths are included.")


def cmd_export(args: argparse.Namespace) -> int:
    loaded = load(_directories(args))
    document = build_export(loaded)
    text = json.dumps(document, indent=2, default=_json_default, ensure_ascii=True) + "\n"
    if args.out:
        try:
            atomic_write(Path(args.out), text)
        except OSError as exc:
            print(f"Could not write {args.out}: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"{export_summary(document)}\nWritten to {args.out}")
    else:
        sys.stdout.write(text)
        print(export_summary(document), file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _bucket() -> dict[str, int]:
    return {"findings": 0, "graded": 0, "correct": 0, "partially_correct": 0, "wrong": 0,
            "reviews": 0, "reviews_graded": 0, "agree": 0, "partial": 0, "disagree": 0,
            "on_graded_outputs": 0, "false_approvals": 0, "false_rejections": 0, "agreements": 0}


def _add_review(bucket: dict[str, int], review: dict[str, Any], human_verdict: str | None) -> None:
    bucket["reviews"] += 1
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
    if human_verdict in ("correct", "flawed") and review.get("vote") in ("approve", "revise"):
        bucket["on_graded_outputs"] += 1
        if review["vote"] == "approve" and human_verdict == "flawed":
            bucket["false_approvals"] += 1
        elif review["vote"] == "revise" and human_verdict == "correct":
            bucket["false_rejections"] += 1
        else:
            bucket["agreements"] += 1


def stats(document: dict[str, Any]) -> dict[str, Any]:
    """Descriptive counts per reviewer configuration and task type from an export document."""
    configs: dict[str, dict[str, Any]] = {}
    jury = Counter()
    for verdict in document.get("verdicts", []):
        human = verdict.get("human_verdict")
        if human in ("correct", "flawed"):
            jury[f"{verdict.get('status')}:{human}"] += 1
        task_type = verdict.get("task_type") or "(none)"
        for review in verdict.get("reviews", []):
            config_id = review.get("config_id") or "(unknown)"
            entry = configs.setdefault(config_id, {
                "config_id": config_id, "judge": review.get("judge"), "role": review.get("role"),
                "provider": review.get("provider"), "model": review.get("model"),
                "rubric_version": review.get("rubric_version"), "all": _bucket(), "task_types": {},
            })
            _add_review(entry["all"], review, human)
            _add_review(entry["task_types"].setdefault(task_type, _bucket()), review, human)
    counts = document.get("counts", {})
    return {
        "verdicts": counts.get("verdicts", len(document.get("verdicts", []))),
        "producer_grades": counts.get("producer_grades", 0),
        "graded_findings": counts.get("graded_findings", 0),
        "jury_status_vs_producer_grade": dict(sorted(jury.items())),
        "configurations": sorted(configs.values(), key=lambda c: (-c["all"]["graded"], c["judge"] or "")),
    }


DISCLAIMER = ("These are descriptive counts of human grades, not reputation weights or calibrated "
              "probabilities. Nothing in AgentJury reads them to change a verdict.")


def _bucket_text(bucket: dict[str, int]) -> str:
    return (f"findings {bucket['findings']} (graded {bucket['graded']}: correct {bucket['correct']}, "
            f"partially_correct {bucket['partially_correct']}, wrong {bucket['wrong']}); "
            f"reviews graded {bucket['reviews_graded']}/{bucket['reviews']} (agree {bucket['agree']}, "
            f"partial {bucket['partial']}, disagree {bucket['disagree']}); on {bucket['on_graded_outputs']} graded "
            f"outputs: false approvals {bucket['false_approvals']}, false rejections {bucket['false_rejections']}, "
            f"agreements {bucket['agreements']}")


def stats_lines(result: dict[str, Any]) -> list[str]:
    lines = [f"Adjudication stats: {result['graded_findings']} graded findings in {result['verdicts']} verdicts "
             f"({result['producer_grades']} with a producer grade).", DISCLAIMER, ""]
    lines.append("Reviewer configurations (each configuration is counted on its own, even when it shares a model)")
    if not result["configurations"]:
        lines.append("  No reviews found.")
    for config in result["configurations"]:
        lines.append(f"  {escape_controls(str(config['judge']))}  {escape_controls(str(config['model']))}  "
                     f"rubric {config['rubric_version']}  config {config['config_id']}")
        lines.append(f"    all task types: {_bucket_text(config['all'])}")
        for task_type, bucket in sorted(config["task_types"].items()):
            lines.append(f"    {escape_controls(task_type)}: {_bucket_text(bucket)}")
    lines.append("")
    pairs = result["jury_status_vs_producer_grade"]
    if pairs:
        lines.append("Jury status against producer grade: "
                     + ", ".join(f"{key.replace(':', ' with ')} {count}" for key, count in pairs.items()))
    else:
        lines.append("Jury status against producer grade: no producer grades yet.")
    return lines


def cmd_stats(args: argparse.Namespace) -> int:
    if args.source:
        try:
            document = json.loads(Path(args.source).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("Cannot read the export file as JSON.", file=sys.stderr)
            return 1
        if not isinstance(document, dict) or document.get("kind") != EXPORT_KIND:
            print("Not an AgentJury adjudication export.", file=sys.stderr)
            return 1
    else:
        document = json.loads(json.dumps(build_export(load(_directories(args))), default=_json_default))
    result = stats(document)
    if args.json:
        result["disclaimer"] = DISCLAIMER
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n".join(stats_lines(result)))
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    group = sub.add_parser("adjudication", help="What needs grading, a text-free export of grades, and descriptive counts.")
    commands = group.add_subparsers(dest="adjudication_command", required=True)
    directory_help = "Verdict directory; repeatable (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts)."

    p = commands.add_parser("pending", help="List ungraded findings, most informative first, with the grading commands.")
    p.add_argument("--dir", action="append", help=directory_help)
    p.add_argument("-n", type=int, help="Show at most this many verdicts.")
    p.add_argument("--json", action="store_true", help="Print structured data.")
    p.set_defaults(func=cmd_pending)

    e = commands.add_parser("export", help="Write grades and reviewer identities as JSON, with no reviewed text.")
    e.add_argument("--dir", action="append", help=directory_help)
    e.add_argument("--out", help="File to write (default: standard output).")
    e.set_defaults(func=cmd_export)

    s = commands.add_parser("stats", help="Descriptive counts of grades per reviewer configuration and task type.")
    s.add_argument("--dir", action="append", help=directory_help)
    s.add_argument("--from", dest="source", metavar="EXPORT", help="Read an export file instead of verdict directories.")
    s.add_argument("--json", action="store_true", help="Print structured data.")
    s.set_defaults(func=cmd_stats)
