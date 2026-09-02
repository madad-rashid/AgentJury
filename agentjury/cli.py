"""
Command-line interface.

    agentjury review TASK OUTPUT [--panel SPEC] [--roles FILE] [--quorum N] [--task-type T] [--domain D] [--json]
    agentjury roles [--roles FILE]
    agentjury schema [request|verdict]
    agentjury verdicts [--dir DIR] [-n N]
    agentjury adjudicate ID [--judge J] [--finding N LABEL]... [--verdict agree|partial|disagree]
                            [--producer-verdict correct|flawed] [--note TEXT] [--dir DIR]

Verdicts are read from --dir, else $AGENTJURY_VERDICT_DIR, else .agentjury/verdicts.

Exit codes: 0 verified, 1 needs_revision, 2 blocked, 3 insufficient_jury.

TASK and OUTPUT are files (or "-" to read OUTPUT from stdin).
PANEL is a comma-separated list of role:provider pairs, for example
    accuracy:openai,critic:anthropic,executive:openai
Every verdict is saved to .agentjury/verdicts/<request_id>.json so that
reviews accumulate over time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .judges import ROLES, anthropic_judge, load_roles, openai_judge
from .judges.base import Judge
from .panel import Panel
from .protocol import HumanReview, Producer, ReviewRequest, Verdict

DEFAULT_PANEL = "accuracy:openai,critic:anthropic,executive:openai"
VERDICT_DIR = Path(".agentjury") / "verdicts"

PROVIDERS = {
    "openai": openai_judge,
    "anthropic": anthropic_judge,
}

SEVERITY_MARK = {"minor": "-", "major": "!", "blocking": "X"}


# Exit codes, so shell scripts and CI can branch without parsing output.
EXIT = {"verified": 0, "needs_revision": 1, "blocked": 2, "insufficient_jury": 3}


def build_panel(spec: str, quorum: int | None = None) -> Panel:
    judges: list[Judge] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            role, provider = item.split(":")
        except ValueError:
            sys.exit(f"Bad panel entry {item!r}. Use role:provider, e.g. critic:anthropic")
        if role not in ROLES:
            sys.exit(f"Unknown role {role!r}. Known roles: {', '.join(sorted(ROLES))}")
        if provider not in PROVIDERS:
            sys.exit(f"Unknown provider {provider!r}. Known providers: {', '.join(PROVIDERS)}")
        judges.append(PROVIDERS[provider](role))
    return Panel(judges, quorum=quorum)


def read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def save(verdict: Verdict) -> Path:
    VERDICT_DIR.mkdir(parents=True, exist_ok=True)
    out = VERDICT_DIR / f"{verdict.request_id}.json"
    out.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    return out


def print_verdict(verdict: Verdict) -> None:
    print(verdict.render())
    print(f"jury confidence index {verdict.confidence:.0%}  (heuristic, not a probability)")
    if verdict.status == "insufficient_jury":
        voters = verdict.responded - verdict.abstained
        providers = len({r.provider for r in verdict.reviews if r.vote != "abstain"})
        print(f"Insufficient jury: {voters} of {verdict.requested} judges voted (quorum {verdict.quorum}), "
              f"from {providers} provider(s). No verdict.")
    print()
    for r in verdict.reviews:
        arrow = {"approve": "▲", "revise": "▼", "abstain": "–"}[r.vote]
        meta = f"{r.latency_ms / 1000:.1f}s" if r.latency_ms is not None else ""
        print(f"{arrow} {r.score:>2.0f}  {r.judge:<22} {r.reason}  [{meta}]")
        for f in r.findings:
            print(f"        {SEVERITY_MARK[f.severity]} {f.text}")
    for e in verdict.errors:
        print(f"!  {e}")


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
        path = save(verdict)
        if not args.json:
            print(f"\nsaved {path}")

    return EXIT[verdict.status]


def verdict_dir(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "dir", None) or os.environ.get("AGENTJURY_VERDICT_DIR") or VERDICT_DIR)


def load_verdict(args: argparse.Namespace) -> tuple[Path, Verdict]:
    ref = args.request_id
    path = Path(ref)
    if not path.is_file():
        d = verdict_dir(args)
        candidates = sorted(d.glob(f"{ref}*.json")) if d.is_dir() else []
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
        print(f"{v.request_id}  {v.created_at:%Y-%m-%d %H:%M}  {v.render()}{mark}{prod}")
    return 0


def cmd_adjudicate(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    path, v = load_verdict(args)
    now = datetime.now(timezone.utc)
    changed: list[str] = []

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
            target.adjudication = label
            target.adjudicated_at = now
            changed.append(f"{review.judge} finding {ref}: {label}")
        if args.verdict:
            review.human_review = HumanReview(verdict=args.verdict, note=args.note, reviewed_at=now)
            changed.append(f"{review.judge} review: {args.verdict}")

    if args.producer_verdict:
        v.human_verdict = args.producer_verdict
        v.human_note = args.note
        v.adjudicated_at = now
        changed.append(f"producer output: {args.producer_verdict}")

    if not changed:
        sys.exit("Nothing to record. Give --finding, --verdict, or --producer-verdict.")

    path.write_text(v.model_dump_json(indent=2), encoding="utf-8")
    print(f"{v.request_id}  {path}")
    for c in changed:
        print(f"  {c}")
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


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="agentjury", description="Peer review for AI agent output.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("review", help="Review an agent's output with a panel of judges.")
    p.add_argument("task", help="File containing the task the agent was given.")
    p.add_argument("output", help="File containing the agent's output, or - for stdin.")
    p.add_argument("--context", help="File with background the judges should know.")
    p.add_argument("--panel", default=os.environ.get("AGENTJURY_PANEL", DEFAULT_PANEL),
                   help=f"role:provider pairs, comma-separated (default: {DEFAULT_PANEL})")
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
    p.set_defaults(func=cmd_review)

    r = sub.add_parser("roles", help="List available judge roles.")
    r.add_argument("--roles", default=os.environ.get("AGENTJURY_ROLES"), help="JSON file of extra roles.")
    r.set_defaults(func=cmd_roles)

    vl = sub.add_parser("verdicts", help="List saved verdicts, newest first.")
    vl.add_argument("--dir", help="Verdict directory (default: $AGENTJURY_VERDICT_DIR or .agentjury/verdicts).")
    vl.add_argument("-n", type=int, default=20, help="How many to show.")
    vl.set_defaults(func=cmd_verdicts)

    a = sub.add_parser("adjudicate", help="Record a human judgement on a saved verdict.")
    a.add_argument("request_id", help="Verdict id (or unique prefix), or a path to its JSON file.")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
