"""
Command-line interface.

    agentjury review TASK OUTPUT [--context FILE] [--panel SPEC] [--task-type T] [--domain D] [--json]
    agentjury roles
    agentjury schema

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

from .judges import ROLES, anthropic_judge, openai_judge
from .judges.base import Judge
from .panel import Panel
from .protocol import Producer, ReviewRequest, Verdict

DEFAULT_PANEL = "accuracy:openai,critic:anthropic,executive:openai"
VERDICT_DIR = Path(".agentjury") / "verdicts"

PROVIDERS = {
    "openai": openai_judge,
    "anthropic": anthropic_judge,
}

SEVERITY_MARK = {"minor": "-", "major": "!", "blocking": "X"}


def build_panel(spec: str) -> Panel:
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
    return Panel(judges)


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
    print(f"confidence {verdict.confidence:.0%}")
    print()
    for r in verdict.reviews:
        arrow = "▲" if r.vote == "approve" else "▼"
        meta = f"{r.latency_ms / 1000:.1f}s" if r.latency_ms is not None else ""
        print(f"{arrow} {r.score:>2.0f}  {r.judge:<22} {r.reason}  [{meta}]")
        for f in r.findings:
            print(f"        {SEVERITY_MARK[f.severity]} {f.text}")
    for e in verdict.errors:
        print(f"!  {e}")


def cmd_review(args: argparse.Namespace) -> int:
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
    verdict = build_panel(args.panel).review(request)

    if args.json:
        print(verdict.model_dump_json(indent=2))
    else:
        print_verdict(verdict)

    if not args.no_save:
        path = save(verdict)
        if not args.json:
            print(f"\nsaved {path}")

    # Exit code lets scripts and CI branch on the result.
    return 0 if verdict.status == "verified" else 1


def cmd_roles(_: argparse.Namespace) -> int:
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
    r.set_defaults(func=cmd_roles)

    s = sub.add_parser("schema", help="Print the JSON schema for the protocol objects.")
    s.add_argument("object", choices=["request", "verdict"], nargs="?", default="verdict")
    s.set_defaults(func=cmd_schema)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
