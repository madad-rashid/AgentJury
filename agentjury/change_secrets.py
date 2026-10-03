"""
Deterministic, heuristic secret detection for text that would leave the machine.

Matches report a source, line and rule, never the matched value. A clean scan
is not proof that text contains no secret: formats change, and a credential
without a recognizable shape is invisible to these rules.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("stripe_live_key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{16,}")),
    # OpenAI, Anthropic (sk-ant-) and OpenRouter (sk-or-) keys share this shape.
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{30,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
)

# A quoted value assigned to a name that ends in a credential word, with any
# prefix (DB_PASSWORD, OPENAI_API_KEY, aws_secret_access_key). The name must
# start an identifier, which also keeps matching linear on long identifiers.
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:[A-Za-z0-9]+[_-])*"
    r"(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|secret|"
    r"(?:api|access|auth|refresh|bearer|bot|session)[_-]?token|password|passwd)"
    r"[\"']?\s*(?::|=|=>|:=)\s*(?P<quote>[\"'])(?P<value>[^\"'\s]{8,})(?P=quote)"
)
_PLACEHOLDER_PREFIXES = ("your", "example", "dummy", "fake", "test", "sample", "placeholder",
                         "changeme", "redacted", "insert", "replace")

# Environment variable names whose values are treated as secrets, by word.
_SECRET_WORDS = frozenset({"KEY", "KEYS", "APIKEY", "TOKEN", "TOKENS", "SECRET", "SECRETS",
                           "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS", "AUTH", "PAT"})
_MIN_ENV_VALUE = 12
# Rooted POSIX or Windows paths (sockets, files) are not secrets. Matched as text,
# because os.path.isabs differs by platform and Python version.
_PATH_VALUE = re.compile(r"^(?:[A-Za-z]:)?[\\/]")


@dataclass(frozen=True)
class SecretMatch:
    """Where a possible secret is. Deliberately has no field for its value."""

    source: str
    line: int
    rule: str
    variable: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source}@{self.line}:{self.rule}"

    def describe(self) -> str:
        suffix = f" (value of ${self.variable})" if self.variable else ""
        return f"{self.id}{suffix}"


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(ch in value for ch in "<>{}$*%") or "..." in value or "xxx" in lowered:
        return True
    return lowered.startswith(_PLACEHOLDER_PREFIXES) or len(set(lowered)) <= 2


def secret_env_values(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Values of secret-named environment variables, mapped to a variable name."""
    environ = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for name, value in environ.items():
        words = set(re.split(r"[^A-Z0-9]+", name.upper()))
        if not words & _SECRET_WORDS:
            continue
        candidate = value.strip()
        if (len(candidate) < _MIN_ENV_VALUE or _PATH_VALUE.match(candidate)
                or candidate.lower() in ("true", "false")):
            continue
        values.setdefault(candidate, name)
    return values


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan(sources: list[tuple[str, str]], environ: Mapping[str, str] | None = None) -> list[SecretMatch]:
    """Possible secrets in each (source, text) pair, in order, one per source/line/rule."""
    env_values = secret_env_values(environ)
    found: dict[tuple[str, int, str], SecretMatch] = {}

    def add(match: SecretMatch) -> None:
        found.setdefault((match.source, match.line, match.rule), match)

    for source, text in sources:
        for rule, pattern in _RULES:
            for hit in pattern.finditer(text):
                add(SecretMatch(source, _line(text, hit.start()), rule))
        for hit in _ASSIGNMENT.finditer(text):
            if not _placeholder(hit.group("value")):
                add(SecretMatch(source, _line(text, hit.start("value")), "credential_assignment"))
        for value, name in env_values.items():
            start = text.find(value)
            while start != -1:
                add(SecretMatch(source, _line(text, start), "environment_value", name))
                start = text.find(value, start + 1)
    return list(found.values())
