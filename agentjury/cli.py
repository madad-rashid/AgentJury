"""
Command-line interface.

    agentjury review TASK OUTPUT [--panel SPEC] [--roles FILE] [--quorum N] [--task-type T] [--domain D] [--json]
    agentjury roles [--roles FILE]
    agentjury schema [request|verdict]
    agentjury verdicts [--dir DIR] [-n N]
    agentjury adjudicate ID [--judge J] [--finding N LABEL]... [--verdict agree|partial|disagree]
                            [--producer-verdict correct|flawed] [--note TEXT] [--dir DIR]
    agentjury change candidates|prepare|send|status ...   (see agentjury/change_review.py)

Verdicts are saved to and read from --dir, else $AGENTJURY_VERDICT_DIR, else .agentjury/verdicts.

Exit codes: 0 verified, 1 needs_revision, 2 blocked, 3 insufficient_jury.
`agentjury change` adds 6 for a refusal (nothing sent) and 7 for a stale review.

TASK and OUTPUT are files (or "-" to read OUTPUT from stdin).
PANEL is a comma-separated list of role:provider[:model] entries, for example
    accuracy:openai,critic:openrouter:anthropic/claude-sonnet-4
Every verdict is saved to .agentjury/verdicts/<request_id>-<run_id>.json so that
reviews accumulate over time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from .judges import ROLES, load_roles
from . import __version__, SCHEMA_VERSION
from . import panel_config
from . import benchmark
from . import change_review
from .benchmark_audit import audit_report
from . import benchmark_cases
from .benchmark_cases import load_cases
from .benchmark_score import score
from .display import verdict_lines
from .local_store import DEFAULT_VERDICT_DIR, atomic_write as _atomic_write
from .panel import Panel
from .protocol import HumanReview, Producer, ReviewRequest, Verdict

DEFAULT_PANEL = "accuracy:openai,critic:anthropic,executive:openai"
VERDICT_DIR = DEFAULT_VERDICT_DIR


# Exit codes, so shell scripts and CI can branch without parsing output.
EXIT = {"verified": 0, "needs_revision": 1, "blocked": 2, "insufficient_jury": 3}


def build_panel(spec: str, quorum: int | None = None) -> Panel:
    try:
        return panel_config.build_panel(spec, quorum=quorum)
    except ValueError as exc:
        sys.exit(str(exc))
    except ImportError as exc:
        message = str(exc)
        sys.exit(message if "package is not installed. Run: pip install" in message
                 else "Could not load panel dependency.")


def read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def save(verdict: Verdict, directory: Path = VERDICT_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / verdict.filename
    out.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return out


def print_verdict(verdict: Verdict) -> None:
    print("\n".join(verdict_lines(verdict)))


def cmd_review(args: argparse.Namespace) -> int:
    if args.roles:
        load_roles(args.roles)
    request = ReviewRequest(
        task=read(args.task),
        output=read(args.output),
        context=read(args.context) if args.context else None,
        task_type=args.task_type,
        domain=args.domain,
        producer=Producer(
            agent=args.agent,
            framework=args.framework,
            provider=args.producer_provider,
            model=args.producer_model,
        ),
    )
    verdict = build_panel(args.panel, quorum=args.quorum).review(request)

    if args.json:
        print(verdict.model_dump_json(indent=2))
    else:
        print_verdict(verdict)

    if not args.no_save:
        path = save(verdict, verdict_dir(args))
        if not args.json:
            print(f"\nsaved {path}")

    return EXIT[verdict.status]


def verdict_dir(args: argparse.Namespace) -> Path:
    from .local_store import verdict_dir as resolve
    return resolve(getattr(args, "dir", None))


def load_verdict(args: argparse.Namespace) -> tuple[Path, Verdict]:
    ref = args.request_id
    path = Path(ref)
    if not path.is_file():
        d = verdict_dir(args)
        candidates = sorted(f for f in d.glob("*.json") if ref in f.stem) if d.is_dir() else []
        if len(candidates) != 1:
            hint = f"{len(candidates)} matches" if candidates else "no match"
            sys.exit(f"Cannot find verdict {ref!r} in {d} ({hint}). Use `agentjury verdicts --dir {d}` to list.")
        path = candidates[0]
    return path, Verdict.model_validate_json(path.read_text(encoding="utf-8"))


def cmd_verdicts(args: argparse.Namespace) -> int:
    d = verdict_dir(args)
    files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True) if d.is_dir() else []
    if not files:
        print(f"No verdicts in {d}")
        return 0
    print(f"{d}\n")
    for f in files[: args.n]:
        v = Verdict.model_validate_json(f.read_text(encoding="utf-8"))
        graded = sum(1 for r in v.reviews for fi in r.findings if fi.adjudication)
        total = sum(len(r.findings) for r in v.reviews)
        mark = f"  [adjudicated {graded}/{total}]" if graded else ""
        prod = f"  producer:{v.human_verdict}" if v.human_verdict else ""
        print(f"run {v.run_id}  req {v.request_id}  {v.created_at:%Y-%m-%d %H:%M}  {v.render()}{mark}{prod}")
    return 0


ADJUDICATION_LOG = "adjudications.jsonl"


def _adjudicator() -> str:
    import getpass
    return os.environ.get("AGENTJURY_ADJUDICATOR") or getpass.getuser()


def log_event(directory: Path, event: dict) -> None:
    """Append one event idempotently, preserving existing history verbatim.

    The caller holds the directory lock. Atomic replacement prevents a torn
    final JSONL line; retained event IDs make replay after interruption safe.
    """
    event = {"event_id": uuid4().hex[:12], **event}
    path = directory / ADJUDICATION_LOG
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for line in text.splitlines():
        old = json.loads(line)
        if old.get("event_id") == event["event_id"]:
            if old != event:
                raise ValueError("Conflicting adjudication event identity.")
            return
    if text and not text.endswith("\n"):
        text += "\n"
    _atomic_write(path, text + json.dumps(event, default=str) + "\n")


@contextmanager
def _adjudication_lock(directory: Path):
    """Cross-process lock released by the OS on interruption, including Windows."""
    with (directory / ".adjudication.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cmd_adjudicate(args: argparse.Namespace) -> int:
    path, _ = load_verdict(args)
    try:
        with _adjudication_lock(path.parent):
            return _adjudicate_locked(args, path)
    except OSError:
        sys.exit("Could not persist adjudication or acquire its directory lock; retry after resolving the storage issue.")


def _publish_pending(path: Path, verdict: Verdict) -> None:
    if not verdict.pending_adjudication_events:
        return
    try:
        for event in verdict.pending_adjudication_events:
            log_event(path.parent, event)
        verdict.pending_adjudication_events = []
        _atomic_write(path, verdict.model_dump_json(indent=2))
    except (OSError, ValueError):
        sys.exit("Adjudication saved with pending audit events. Retry adjudication to recover the history; no event is lost.")


def _adjudicate_locked(args: argparse.Namespace, path: Path) -> int:
    from datetime import datetime, timezone

    v = Verdict.model_validate_json(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    who = _adjudicator()
    base = {"at": now.isoformat(timespec="seconds"), "adjudicator": who,
            "run_id": v.run_id, "request_id": v.request_id, "note": args.note}
    changed: list[str] = []
    proposed = []
    targets = []

    if args.finding or args.verdict:
        if not args.judge:
            sys.exit("--judge is required when grading findings or a review. Judges: " +
                     ", ".join(r.judge for r in v.reviews))
        matches = [r for r in v.reviews if r.judge == args.judge or r.review_id == args.judge
                   or r.role == args.judge]
        if len(matches) != 1:
            sys.exit(f"--judge {args.judge!r} matched {len(matches)} reviews. Judges: " +
                     ", ".join(r.judge for r in v.reviews))
        review = matches[0]
        for ref, label in args.finding or []:
            if label not in ("correct", "partially_correct", "wrong"):
                sys.exit(f"Finding label must be correct, partially_correct, or wrong; got {label!r}.")
            target = None
            if ref.isdigit() and 1 <= int(ref) <= len(review.findings):
                target = review.findings[int(ref) - 1]
            else:
                target = next((f for f in review.findings if f.id == ref), None)
            if target is None:
                sys.exit(f"{review.judge} has no finding {ref!r} (it has {len(review.findings)}).")
            if any(target.id == prior.id for prior, _, _ in targets):
                sys.exit("A finding can be graded only once in one adjudication command.")
            targets.append((target, ref, label))
        # All references and labels are valid before changing state or history.
        for target, ref, label in targets:
            proposed.append({**base, "kind": "finding", "review_id": review.review_id,
                                    "judge": review.judge, "config_id": review.config_id,
                                    "finding_id": target.id, "old": target.adjudication, "new": label})
            target.adjudication = label
            target.adjudicated_at = now
            changed.append(f"{review.judge} finding {ref}: {label}")
        if args.verdict:
            old = review.human_review.verdict if review.human_review else None
            proposed.append({**base, "kind": "review", "review_id": review.review_id,
                                    "judge": review.judge, "config_id": review.config_id,
                                    "old": old, "new": args.verdict})
            review.human_review = HumanReview(verdict=args.verdict, note=args.note, reviewed_at=now)
            changed.append(f"{review.judge} review: {args.verdict}")

    if args.producer_verdict:
        proposed.append({**base, "kind": "producer", "old": v.human_verdict, "new": args.producer_verdict})
        v.human_verdict = args.producer_verdict
        v.human_note = args.note
        v.adjudicated_at = now
        changed.append(f"producer output: {args.producer_verdict}")

    if not changed:
        sys.exit("Nothing to record. Give --finding, --verdict, or --producer-verdict.")

    v.pending_adjudication_events.extend({"event_id": uuid4().hex, **event} for event in proposed)
    _atomic_write(path, v.model_dump_json(indent=2))
    _publish_pending(path, v)
    print(f"run {v.run_id}  {path}")
    for c in changed:
        print(f"  {c}")
    print(f"  logged by {who} -> {path.parent / ADJUDICATION_LOG}")
    return 0


def cmd_roles(args: argparse.Namespace) -> int:
    if args.roles:
        load_roles(args.roles)
    for name, desc in ROLES.items():
        print(f"{name:<10} {desc}")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    model = {"request": ReviewRequest, "verdict": Verdict}[args.object]
    print(json.dumps(model.model_json_schema(), indent=2))
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    if args.retry_errors and not args.resume:
        print("Benchmark configuration error: --retry-errors requires --resume.", file=sys.stderr)
        return 5
    try:
        cases, pack_hash = load_cases(args.cases, pack=args.pack)
        try:
            candidates = benchmark.prepare(cases, args.panel)
        except (ValueError, ImportError) as exc:
            message = str(exc)
            if (message.startswith("Panel setup failed (")
                    or isinstance(exc, ImportError) and "package is not installed. Run: pip install" not in message):
                message = "Invalid benchmark configuration or report."
            print(message, file=sys.stderr)
            return 5
        if args.max_calls <= 0:
            raise ValueError("--max-calls must be positive.")
        report_path = args.resume or (
            Path(".agentjury") / "benchmarks" /
            f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.json"
        )
        if not args.json:
            print(f"Preflight: {len(cases)} cases, {len(candidates)} candidate panels, "
                  f"{benchmark.distinct_jobs(cases, candidates)} distinct jobs, "
                  f"maximum attempts {benchmark.maximum_attempts(cases, candidates)}, "
                  f"call cap {args.max_calls}, report {report_path}")
        report = benchmark.run(
            cases, pack_hash, candidates, report_path=report_path,
            max_calls=args.max_calls, resume=bool(args.resume), retry_errors=args.retry_errors,
            progress=None if args.json else print,
            on_snapshot=lambda snapshot: score(snapshot, cases, candidates),
        )
    except (ValueError, OSError) as exc:
        message = str(exc)
        if not (message.startswith("Invalid case file") or message.startswith("Panel contains a duplicate")
                or message.startswith("--max-calls") or message.startswith("Invalid resume")):
            message = "Invalid benchmark configuration or report."
        print(message, file=sys.stderr)
        return 5

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for spec, rows in report["outcomes"].items():
            print(f"\nPanel {spec}")
            for row in rows:
                print(f"  {row['case_id']} ({row['label']}): {row['status']}")
            totals = report["summary"][spec]
            latency = totals["median_latency_ms"]
            latency_text = "n/a" if latency is None else f"{latency:g} ms"
            print(f"  unsafe approvals {totals['unsafe_approvals']}/{totals['unsafe_denominator']}; "
                  f"missed blocks {totals['missed_blocks']}/{totals['injected_total']}; "
                  f"false rejections {totals['false_rejections']}/{totals['correct_total']}; "
                  f"unavailable {totals['unavailable']}/{totals['total']}; "
                  f"completed {totals['completed']}/{totals['total']}; "
                  f"actionable {totals['actionable']}/{totals['total']}; "
                  f"median judge latency {latency_text}")
        if report["recommendation"]:
            tied = len(report["recommendation"]["panels"]) > 1
            print("\nTied provisional panel suggestions from these cases:"
                  if tied else "\nProvisional panel suggestion from these cases:")
            for spec in report["recommendation"]["panels"]:
                print(f"  --panel {spec}")
        else:
            print(f"\nNo panel recommendation: {report['recommendation_reason']}")
        print(f"Report saved: {report_path}")
    return 0 if report["state"] == "complete" else 4


def cmd_benchmark_audit(args: argparse.Namespace) -> int:
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result = audit_report(report)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        print("Invalid benchmark report.", file=sys.stderr)
        return 5

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    def label(value: str) -> str:
        return json.dumps(value, ensure_ascii=True)

    print(f"Offline benchmark audit: {result['case_count']} labeled cases "
          f"({result['state']}; descriptive counts)")
    print("\nReviewers")
    for stats in result["judges"].values():
        print(f"  {label(stats['name'])}: {stats['correct']}/{stats['judged']} correct votes; "
              f"false approvals {stats['false_approvals']}; "
              f"false rejections {stats['false_rejections']}; "
              f"unavailable {stats['unavailable']}; pending {stats['pending']}")
    print("\nShared errors")
    if not result["pairs"]:
        print("  No reviewer pairs in this report.")
    for pair in result["pairs"]:
        left, right = pair["judge_ids"]
        cases = ", ".join(label(case_id) for case_id in pair["both_wrong"]) or "none"
        print(f"  {label(result['judges'][left]['name'])} + "
              f"{label(result['judges'][right]['name'])}: "
              f"{len(pair['both_wrong'])}/{pair['compared']} both wrong; cases {cases}")
    print("\nPanel majority versus best observed reviewer (same completed cases)")
    for spec, comparison in result["panels"].items():
        majority = comparison["majority"]
        best = comparison["best_single"]
        print(f"  {label(spec)}: {comparison['common_cases']} common cases; "
              f"majority {majority['correct']} correct, "
              f"{majority['false_approvals']} false approvals, "
              f"{majority['false_rejections']} false rejections, "
              f"{majority['ties']} ties")
        if best is not None:
            names = ", ".join(label(result["judges"][judge_id]["name"])
                              for judge_id in comparison["best_judge_ids"])
            print(f"    best observed reviewer {names}: {best['correct']} correct, "
                  f"{best['false_approvals']} false approvals, "
                  f"{best['false_rejections']} false rejections")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    load_dotenv()
    parser = argparse.ArgumentParser(prog="agentjury", description="Peer review for AI agent output.")
    parser.add_argument("--version", action="version",
                        version=f"agentjury {__version__} (schema {SCHEMA_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("review", help="Review an agent's output with a panel of judges.")
    p.add_argument("task", help="File containing the task the agent was given.")
    p.add_argument("output", help="File containing the agent's output, or - for stdin.")
    p.add_argument("--context", help="File with background the judges should know.")
    p.add_argument("--panel", default=os.environ.get("AGENTJURY_PANEL", DEFAULT_PANEL),
                   help=f"role:provider[:model] entries, comma-separated (default: {DEFAULT_PANEL})")
    p.add_argument("--roles", default=os.environ.get("AGENTJURY_ROLES"),
                   help="JSON file of extra roles {name: description}, e.g. a domain expert.")
    p.add_argument("--quorum", type=int, help="Minimum judges that must respond (default: majority).")
    p.add_argument("--task-type", help="Kind of work, e.g. financial_analysis, code_review, summary.")
    p.add_argument("--domain", help="Subject area, e.g. private_credit, python.")
    p.add_argument("--agent", help="Name of the agent that did the work.")
    p.add_argument("--framework", help="Framework the agent runs on, e.g. hermes.")
    p.add_argument("--producer-provider", help="Provider of the model that did the work, e.g. anthropic.")
    p.add_argument("--producer-model", help="Model that did the work, e.g. claude-fable-5-1.")
    p.add_argument("--json", action="store_true", help="Print the full verdict as JSON.")
    p.add_argument("--no-save", action="store_true", help="Do not write the verdict to .agentjury/.")
    p.add_argument("--dir", help="Verdict directory (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts).")
    p.set_defaults(func=cmd_review)

    r = sub.add_parser("roles", help="List available judge roles.")
    r.add_argument("--roles", default=os.environ.get("AGENTJURY_ROLES"), help="JSON file of extra roles.")
    r.set_defaults(func=cmd_roles)

    vl = sub.add_parser("verdicts", help="List saved verdicts, newest first.")
    vl.add_argument("--dir", help="Verdict directory (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts).")
    vl.add_argument("-n", type=int, default=20, help="How many to show.")
    vl.set_defaults(func=cmd_verdicts)

    a = sub.add_parser("adjudicate", help="Record a human judgement on a saved verdict.")
    a.add_argument("request_id", metavar="ID", help="run_id or request_id (or unique fragment), or a path to the JSON file.")
    a.add_argument("--dir", help="Verdict directory (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts).")
    a.add_argument("--judge", help="Which review to grade: judge name (critic/anthropic), role, or review_id.")
    a.add_argument("--finding", nargs=2, action="append", metavar=("N", "LABEL"),
                   help="Grade finding N (1-based, as shown) as correct, partially_correct, or wrong. Repeatable.")
    a.add_argument("--verdict", choices=["agree", "partial", "disagree"], help="Your overall view of that judge's review.")
    a.add_argument("--producer-verdict", choices=["correct", "flawed"], help="Your view of the agent's output itself.")
    a.add_argument("--note", help="Free-text reason, stored with the review and/or producer verdict.")
    a.set_defaults(func=cmd_adjudicate)

    s = sub.add_parser("schema", help="Print the JSON schema for the protocol objects.")
    s.add_argument("object", choices=["request", "verdict"], nargs="?", default="verdict")
    s.set_defaults(func=cmd_schema)

    b = sub.add_parser("benchmark", help="Compare explicit panels on labeled cases.")
    source = b.add_mutually_exclusive_group()
    source.add_argument("--cases", type=Path, help="UTF-8 JSON case file (default: built-in starter cases).")
    source.add_argument("--pack", choices=sorted(benchmark_cases.PACKS), default="starter",
                        help="Built-in case pack: starter (short answers) or code (unified diffs).")
    b.add_argument("--panel", action="append", required=True,
                   help="Candidate panel in the same syntax as review; repeat to compare.")
    b.add_argument("--max-calls", type=int, default=20,
                   help="Maximum provider completion attempts this run (default: 20); "
                        "an unfinished job may repeat on resume.")
    b.add_argument("--resume", type=Path, help="Continue a saved benchmark report.")
    b.add_argument("--retry-errors", action="store_true", help="Retry failed jobs while retaining successes.")
    b.add_argument("--json", action="store_true", help="Print the saved report as JSON only.")
    b.set_defaults(func=cmd_benchmark)

    a = sub.add_parser("benchmark-audit", help="Analyze a saved benchmark report offline.")
    a.add_argument("report", type=Path, help="Saved benchmark JSON report.")
    a.add_argument("--json", action="store_true", help="Print structured audit data.")
    a.set_defaults(func=cmd_benchmark_audit)

    change_review.add_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
