"""Local files AgentJury writes: atomic replacement and verdict directory resolution."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

DEFAULT_VERDICT_DIR = Path(".agentjury") / "verdicts"


def atomic_write(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` so a reader sees the old file or the new one, never a torn one."""
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


def verdict_dir(explicit: str | os.PathLike | None, default: Path = DEFAULT_VERDICT_DIR) -> Path:
    """``--dir``, else ``$AGENTJURY_VERDICT_DIR``, else ``default``."""
    return Path(explicit or os.environ.get("AGENTJURY_VERDICT_DIR") or default)


def verdict_dirs(explicit: list[str] | None, default: Path = DEFAULT_VERDICT_DIR) -> list[Path]:
    """Every ``--dir`` given, or the single resolved default; the same directory is read once."""
    given = [Path(d) for d in explicit] if explicit else [verdict_dir(None, default)]
    unique: list[Path] = []
    seen: set[str] = set()
    for directory in given:
        key = os.path.normcase(os.path.realpath(directory))
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique
