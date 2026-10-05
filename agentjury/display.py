"""Terminal rendering of a verdict, shared by the review and change commands.

Reviewer names, reasons, findings and errors are model or endpoint text and
are escaped before they reach the terminal. The confidence figure is always
labelled as a heuristic.
"""

from __future__ import annotations

from .judges.evidence import _normalize
from .protocol import Verdict
from .reviewer_guard import escape_controls

SEVERITY_MARK = {"minor": "-", "major": "!", "blocking": "X"}
ARROW = {"approve": "▲", "revise": "▼", "abstain": "–"}


def verdict_lines(
    verdict: Verdict,
    *,
    numbered: bool = False,
    coverage: str | None = None,
    file_hints: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Lines for a verdict. ``numbered`` lists findings as ``agentjury adjudicate`` counts them;
    ``coverage`` is an extra line after the headline; ``file_hints`` maps normalized diff text
    per file so a finding's output excerpt can name the file it came from."""
    lines = [verdict.render(), f"jury confidence index {verdict.confidence:.0%}  (heuristic, not a probability)"]
    if verdict.status == "insufficient_jury":
        voters = verdict.responded - verdict.abstained
        providers = len({r.provider for r in verdict.reviews if r.vote != "abstain"})
        lines.append(f"Insufficient jury: {voters} of {verdict.requested} judges voted (quorum {verdict.quorum}), "
                     f"from {providers} provider(s). No verdict.")
    if coverage:
        lines.append(coverage)
    if verdict.local_signals:
        lines.append("Local check changed verified to needs_revision: reviewer-directed instruction detected."
                     if verdict.local_guard_applied
                     else "Local check detected a reviewer-directed instruction; status unchanged.")
        lines += [f"  ! {signal.rule_id}: {escape_controls(signal.excerpt)}" for signal in verdict.local_signals]
    lines.append("")
    for review in verdict.reviews:
        meta = f"{review.latency_ms / 1000:.1f}s" if review.latency_ms is not None else ""
        lines.append(f"{ARROW[review.vote]} {review.score:>2.0f}  {escape_controls(review.judge):<22} "
                     f"{escape_controls(review.reason)}  [{meta}]")
        for number, finding in enumerate(review.findings, 1):
            checked = " [excerpts checked]" if finding.evidence is not None else ""
            graded = f" [graded {finding.adjudication}]" if finding.adjudication else ""
            text = escape_controls(finding.text)
            if not numbered:
                lines.append(f"        {SEVERITY_MARK[finding.severity]} {text}{checked}{graded}")
                continue
            where = ""
            evidence = finding.evidence
            if file_hints and evidence is not None and evidence.output_artifact_id is None:
                quote = _normalize(evidence.output_quote)
                files = [path for path, body in file_hints if quote and quote in body]
                where = (f"  ({escape_controls(files[0])})" if len(files) == 1
                         else ("  (several files)" if files else ""))
            lines.append(f"        {number}. [{finding.severity}] {text}{where}{checked}{graded}")
    lines += [f"!  {escape_controls(error)}" for error in verdict.errors]
    return lines
