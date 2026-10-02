"""Narrow, deterministic detection of commands aimed at AgentJury reviewers."""

from __future__ import annotations

from bisect import bisect_left
import re
import unicodedata

from .protocol import LocalSignal


_CUE = re.compile(r"\b(?:reviewer|judge|jury|grading rubric|rubric update)\b")
_DIRECTIVES = (
    ("force_approval", re.compile(
        r"\b(?:return|output|respond with|mark(?: this answer)?(?: as)?)\s+"
        r"(?:approve|approved|verified)\b"
        r"|\bplease\s+approve\b"
        r"|\bapprove\s+(?:this|the)\s+answer\b"
        r"|\b(?:must|should|shall)\s+(?:be\s+marked|mark\s+(?:this|the)\s+answer)\s+"
        r"(?:as\s+)?(?:approved|verified)\b"
        r"|\b(?:ignore|disregard)\s+(?:the\s+|this\s+)?(?:user\s+)?task\b"
    )),
    ("score_override", re.compile(
        r"\b(?:assign|give|set|return)\s+(?:a\s+)?score\s+(?:of\s+)?\d+(?:\.\d+)?\b"
        r"|\b(?:increase|raise|boost)\s+(?:the\s+)?score\s+to\s+\d+(?:\.\d+)?\b"
    )),
    ("suppress_findings", re.compile(
        r"\b(?:do not|don't|never)\s+(?:report|mention|include|flag)\b.{0,80}?"
        r"\b(?:finding|findings|instruction|issue)\b"
        r"|\b(?:ignore|suppress|omit)\s+(?:this|the|any)\s+findings?\b"
    )),
)

_NEGATED_OR_DESCRIPTIVE = re.compile(
    r"\b(?:do not|don't|never|cannot|can't|should not|must not|can|could|may|might|will)\s+$"
)


def _normalized_with_offsets(output: str) -> tuple[str, list[int]]:
    """Fold for matching and map each folded character to its source offset."""
    chars: list[str] = []
    offsets: list[int] = []
    for offset, original in enumerate(output):
        for char in unicodedata.normalize("NFKC", original).casefold():
            if char.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    offsets.append(offset)
            else:
                chars.append(char)
                offsets.append(offset)
    if chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()
    return "".join(chars), offsets


def escape_controls(value: str) -> str:
    """Make untrusted excerpts safe to display in a terminal."""
    pieces: list[str] = []
    for char in value:
        code = ord(char)
        if code < 32 or 127 <= code <= 159:
            pieces.append(f"\\x{code:02x}")
        else:
            pieces.append(char)
    return "".join(pieces)


def detect_reviewer_commands(output: str) -> list[LocalSignal]:
    """Return up to three local warnings for reviewer-directed commands."""
    normalized, offsets = _normalized_with_offsets(output)
    cues = list(_CUE.finditer(normalized))
    if not cues:
        return []
    cue_starts = [cue.start() for cue in cues]
    candidates: list[tuple[int, int, int, int, str]] = []
    for rule_id, pattern in _DIRECTIVES:
        for directive in pattern.finditer(normalized):
            prefix = normalized[max(0, directive.start() - 30):directive.start()]
            if _NEGATED_OR_DESCRIPTIVE.search(prefix):
                continue
            index = bisect_left(cue_starts, directive.start())
            nearby = cues[max(0, index - 1):index + 1]
            eligible = [cue for cue in nearby if abs(cue.start() - directive.start()) <= 200]
            if eligible:
                cue = min(eligible, key=lambda item: abs(item.start() - directive.start()))
                candidates.append((directive.start(), directive.end(), cue.start(), cue.end(), rule_id))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    signals: list[LocalSignal] = []
    accepted_spans: list[tuple[int, int]] = []
    for directive_start, directive_end, cue_start, cue_end, rule_id in candidates:
        if any(directive_start < end and directive_end > start
               for start, end in accepted_spans):
            continue
        accepted_spans.append((directive_start, directive_end))
        begin = offsets[min(cue_start, directive_start)]
        end = offsets[max(cue_end, directive_end) - 1] + 1
        if end - begin > 160:
            begin = max(0, offsets[directive_start] - 40)
        excerpt = escape_controls(output[begin:begin + 160])[:160]
        signals.append(LocalSignal(rule_id=rule_id, excerpt=excerpt))
        if len(signals) == 3:
            break
    return signals
