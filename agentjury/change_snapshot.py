"""
Capture a Git code change for an explicit AgentJury review.

Nothing in this module contacts a reviewer or the network. Git plumbing lists
changed paths; file contents are read only for paths that pass the name and
mode exclusions, symlinks are never followed, and no Git object is written.
A snapshot binds a review to the exact working-tree bytes it covered, so a
later edit makes the review stale.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

DEFAULT_CONTEXT_LINES = 5
MAX_FILE_CHARS = 50_000
MAX_TOTAL_CHARS = 150_000
MAX_READ_BYTES = 10_000_000
STATE_DIR = ".agentjury"

SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"

_DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
               "--src-prefix=a/", "--dst-prefix=b/")
# Literal pathspecs stop names such as ":(glob)x" acting as Git magic; no
# optional lock means listing changes never rewrites the index.
_GIT_ENV = {"GIT_LITERAL_PATHSPECS": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}

# Matched case-insensitively against the file name before any content is read.
SECRET_NAMES = (
    ".env", ".env.*", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "*.ppk", "*.kdbx", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", ".npmrc", ".pypirc",
    ".netrc", "_netrc", ".git-credentials", ".dockercfg", "credentials", "credentials.json",
    "*.tfvars", "*.tfvars.json", "*.tfstate", "*.tfstate.backup", "secrets.*", ".secrets",
)
SECRET_NAME_EXCEPTIONS = ("*.example", "*.sample", "*.template", "*.dist")
SECRET_PATHS = (".claude/settings.local.json", ".docker/config.json", ".kube/config",
                ".aws/credentials", ".aws/config")
SECRET_DIRS = (".ssh", ".gnupg")
LOCKFILES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "bun.lockb", "poetry.lock", "uv.lock", "pipfile.lock", "pdm.lock", "cargo.lock",
    "composer.lock", "gemfile.lock", "go.sum", "packages.lock.json", "pubspec.lock",
    "mix.lock", "flake.lock", "podfile.lock", "gradle.lockfile",
})

SECRET_REASON = "secret-bearing file name; not read"


class ChangeError(Exception):
    """A refusal whose message is safe to print. Nothing has been sent."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


class SkipFile(Exception):
    """A selected path whose contents cannot be reviewed safely."""


ChangeKind = Literal["added", "modified", "deleted", "type_changed", "unmerged"]


@dataclass(frozen=True)
class Candidate:
    """A changed path, classified without reading its contents."""

    path: str
    change: ChangeKind
    tracked: bool
    exclusion: str | None = None


class ChangeFile(BaseModel):
    """One selected path: reviewed with these exact bytes, or not sent and why."""

    model_config = ConfigDict(extra="forbid")

    path: str
    change: ChangeKind
    tracked: bool
    reviewed: bool
    reason: str | None = None
    sha256: str | None = None
    git_blob: str | None = None
    added: int | None = None
    removed: int | None = None
    diff_start: int | None = None
    diff_end: int | None = None


class ChangeSnapshot(BaseModel):
    """The base commit and the reviewed working-tree state of each selected path."""

    model_config = ConfigDict(extra="forbid")

    base: str
    base_commit: str
    head_commit: str | None
    context_lines: int
    files: list[ChangeFile]

    @property
    def reviewed(self) -> list[ChangeFile]:
        return [f for f in self.files if f.reviewed]

    @property
    def omitted(self) -> list[ChangeFile]:
        return [f for f in self.files if not f.reviewed]


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _run_git(root: Path | None, *args: str, input: bytes | None = None,
             literal: bool = True) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in ("GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS")}
    env.update(_GIT_ENV)
    if not literal:
        env.pop("GIT_LITERAL_PATHSPECS")
    try:
        return subprocess.run(["git", *args], cwd=root, input=input, capture_output=True, env=env, check=False)
    except FileNotFoundError:
        raise ChangeError("Git is not installed or not on PATH.") from None


def git(root: Path | None, *args: str, input: bytes | None = None) -> bytes:
    result = _run_git(root, *args, input=input)
    if result.returncode != 0:
        reason = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ChangeError(f"git {args[0]} failed: {reason[0] if reason else 'no message'}")
    return result.stdout


def repo_root(start: Path | None = None) -> Path:
    result = _run_git(start or Path.cwd(), "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise ChangeError("Run this inside a Git work tree.")
    return Path(result.stdout.decode("utf-8").strip())


def resolve_commit(root: Path, rev: str) -> str:
    if not rev or rev.startswith("-"):
        raise ChangeError(f"Invalid base revision {rev!r}.")
    result = _run_git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if result.returncode != 0:
        if rev == "HEAD":
            raise ChangeError("The repository has no commits yet; commit once or pass --base.")
        raise ChangeError(f"Unknown base revision {rev!r}.")
    return result.stdout.decode("ascii").strip()


def head_commit(root: Path) -> str | None:
    result = _run_git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    return result.stdout.decode("ascii").strip() if result.returncode == 0 else None


def is_ignored(root: Path, path: str) -> bool:
    """For fixed internal paths only: check-ignore rejects literal pathspec mode."""
    result = _run_git(root, "check-ignore", "-q", "--no-index", path, literal=False)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Change discovery and classification
# ---------------------------------------------------------------------------


def _decode_path(raw: bytes) -> tuple[str, str | None]:
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), "file name is not valid UTF-8"
    if any(ch in path for ch in "\n\r") or not path.isprintable():
        return path, "file name contains control characters"
    return path, None


def _internal(path: str) -> bool:
    return path == STATE_DIR or path.startswith(STATE_DIR + "/")


def secret_named(path: str) -> bool:
    """True when the path names a likely credential file. Its contents are never read."""
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    parts = lowered.split("/")[:-1]
    if any(part in SECRET_DIRS for part in parts):
        return True
    if any(lowered == p or lowered.endswith("/" + p) for p in SECRET_PATHS):
        return True
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_NAME_EXCEPTIONS):
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_NAMES)


def _exclusion(path: str, modes: tuple[str | None, ...], change: str) -> str | None:
    if secret_named(path):
        return SECRET_REASON
    if SYMLINK_MODE in modes:
        return "symlink; target not followed"
    if GITLINK_MODE in modes:
        return "submodule; not reviewed"
    if change == "unmerged":
        return "unmerged; resolve the conflict first"
    if path.lower().rsplit("/", 1)[-1] in LOCKFILES:
        return "lockfile; not reviewed"
    return None


_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "type_changed", "U": "unmerged"}


def find_candidates(root: Path, base_commit: str) -> list[Candidate]:
    """Tracked changes against the base plus untracked files Git does not ignore."""
    found: dict[str, Candidate] = {}
    tokens = git(root, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                 base_commit, "--").split(b"\0")
    index = 0
    while index + 1 < len(tokens):
        meta, raw_path = tokens[index], tokens[index + 1]
        index += 2
        if not meta.startswith(b":"):
            raise ChangeError("Unexpected git diff output.")
        old_mode, new_mode, _, _, status = meta[1:].decode("ascii").split(" ")[:5]
        path, bad_name = _decode_path(raw_path)
        if _internal(path):
            continue
        change = _STATUS.get(status[:1], "modified")
        found[path] = Candidate(path, change, True,
                                bad_name or _exclusion(path, (old_mode, new_mode), change))

    for raw_path in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw_path:
            continue
        path, bad_name = _decode_path(raw_path)
        if _internal(path):
            continue
        if path in found:
            # Removed from the index but still on disk: neither side is a clean change.
            found[path] = Candidate(path, found[path].change, True,
                                    "removed from the Git index but present on disk; stage or restore it first")
            continue
        if path.endswith("/"):
            found[path] = Candidate(path, "added", False, "nested Git repository; not reviewed")
            continue
        try:
            mode = SYMLINK_MODE if os.path.islink(root / path) else None
        except OSError:
            mode = None
        found[path] = Candidate(path, "added", False, bad_name or _exclusion(path, (mode,), "added"))
    return [found[path] for path in sorted(found)]


def _real(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def repo_relative(raw: str, root: Path, cwd: Path) -> str:
    """A selection or input path as a POSIX path inside the work tree, without following its final component."""
    absolute = Path(os.path.abspath(Path(cwd) / raw))
    real_root = os.path.realpath(root)
    if _real(absolute) == os.path.normcase(real_root):
        return ""
    unresolved = os.path.join(os.path.realpath(absolute.parent), absolute.name)
    if not _inside(os.path.normcase(unresolved), os.path.normcase(real_root)):
        raise ChangeError(f"{raw!r} is outside the repository.")
    return Path(os.path.relpath(unresolved, real_root)).as_posix()


def select(candidates: list[Candidate], requested: list[str], root: Path, cwd: Path) -> list[Candidate]:
    """Every candidate by default; otherwise the named changed files and directories."""
    if not requested:
        return list(candidates)
    chosen: dict[str, Candidate] = {}
    for raw in requested:
        rel = repo_relative(raw, root, cwd)
        prefix = rel.rstrip("/") + "/" if rel else ""
        matches = [c for c in candidates if c.path == rel or c.path.startswith(prefix)]
        if not matches:
            raise ChangeError(f"{raw!r} is not a changed file in this review. "
                              "Run `agentjury change candidates` to list changed files.")
        for candidate in matches:
            chosen[candidate.path] = candidate
    return [chosen[path] for path in sorted(chosen)]


# ---------------------------------------------------------------------------
# Content, diffs and digests
# ---------------------------------------------------------------------------


def _regular_file(root: Path, path: str) -> tuple[Path, os.stat_result] | None:
    full = root / path
    try:
        info = os.lstat(full)
    except FileNotFoundError:
        return None
    except OSError:
        raise SkipFile("unreadable") from None
    if stat.S_ISLNK(info.st_mode):
        raise SkipFile("symlink; target not followed")
    if not stat.S_ISREG(info.st_mode):
        raise SkipFile("not a regular file")
    if not _inside(_real(full), _real(root)):
        raise SkipFile("resolves outside the repository")
    return full, info


def read_worktree(root: Path, path: str, limit: int | None = None) -> bytes | None:
    """Exact bytes of a regular file, or None when it is absent. Never follows symlinks."""
    found = _regular_file(root, path)
    if found is None:
        return None
    full, info = found
    if limit is not None and info.st_size > limit:
        raise SkipFile(f"file larger than {limit:,} bytes; not reviewed")
    try:
        with open(full, "rb") as stream:
            return stream.read()
    except OSError:
        raise SkipFile("unreadable") from None


def worktree_digest(root: Path, path: str) -> str | None:
    """SHA-256 of a regular file's bytes, read in chunks, or None when it is absent."""
    found = _regular_file(root, path)
    if found is None:
        return None
    digest = hashlib.sha256()
    try:
        with open(found[0], "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        raise SkipFile("unreadable") from None
    return digest.hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(root: Path, path: str, data: bytes) -> str | None:
    """The blob ID Git would record for these bytes at this path; nothing is written."""
    result = _run_git(root, "hash-object", f"--path={path}", "--stdin", input=data)
    return result.stdout.decode("ascii").strip() if result.returncode == 0 else None


def _count(diff: str) -> tuple[int, int]:
    added = removed = 0
    in_hunk = False
    for line in diff.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added += 1
        elif in_hunk and line.startswith("-"):
            removed += 1
    return added, removed


def _binary_diff(diff: str) -> bool:
    return any(line.startswith("Binary files ") and line.endswith(" differ") or line == "GIT binary patch"
               for line in diff.split("\n"))


def _untracked_diff(path: str, text: str, executable: bool) -> str:
    """The new-file diff Git would show, built from the bytes already read."""
    header = [f"diff --git a/{path} b/{path}", f"new file mode {'100755' if executable else '100644'}"]
    if not text:
        return "\n".join(header) + "\n"
    lines = text.split("\n")
    complete = text.endswith("\n")
    if complete:
        lines.pop()
    span = f"+1,{len(lines)}" if len(lines) != 1 else "+1"
    body = ["--- /dev/null", f"+++ b/{path}", f"@@ -0,0 {span} @@", *("+" + line for line in lines)]
    if not complete:
        body.append("\\ No newline at end of file")
    return "\n".join(header + body) + "\n"


def _tracked_diff(root: Path, base_commit: str, path: str, context_lines: int) -> bytes:
    return git(root, "diff", *_DIFF_FLAGS, f"--unified={context_lines}", base_commit, "--", path)


def _executable(root: Path, path: str) -> bool:
    try:
        return bool(os.lstat(root / path).st_mode & stat.S_IXUSR) and os.name != "nt"
    except OSError:
        return False


def capture(
    root: Path,
    base: str,
    base_commit: str,
    selected: list[Candidate],
    *,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    max_file_chars: int = MAX_FILE_CHARS,
    max_total_chars: int = MAX_TOTAL_CHARS,
) -> tuple[ChangeSnapshot, str]:
    """Build the reviewed diff and bind it to the bytes it was made from."""
    files: list[ChangeFile] = []
    chunks: list[tuple[ChangeFile, str]] = []
    for candidate in selected:
        def omit(reason: str) -> None:
            files.append(ChangeFile(path=candidate.path, change=candidate.change,
                                    tracked=candidate.tracked, reviewed=False, reason=reason))

        if candidate.exclusion:
            omit(candidate.exclusion)
            continue
        try:
            data = read_worktree(root, candidate.path, MAX_READ_BYTES)
        except SkipFile as exc:
            omit(str(exc))
            continue
        if data is not None and b"\0" in data[:8192]:
            omit("binary content; not reviewed")
            continue
        try:
            if candidate.tracked:
                diff = _tracked_diff(root, base_commit, candidate.path, context_lines).decode("utf-8")
            elif data is None:
                omit("no longer present; not reviewed")
                continue
            else:
                diff = _untracked_diff(candidate.path, data.decode("utf-8"),
                                       _executable(root, candidate.path))
        except UnicodeDecodeError:
            omit("not UTF-8 text; not reviewed")
            continue
        if not diff:
            omit("no textual change")
            continue
        if _binary_diff(diff):
            omit("binary content; not reviewed")
            continue
        if len(diff) > max_file_chars:
            omit(f"diff larger than {max_file_chars:,} characters; not reviewed")
            continue
        try:
            again = read_worktree(root, candidate.path, MAX_READ_BYTES)
        except SkipFile as exc:
            omit(str(exc))
            continue
        if again != data:
            raise ChangeError(f"{candidate.path} changed while the review was being prepared; try again.")
        added, removed = _count(diff)
        item = ChangeFile(
            path=candidate.path, change=candidate.change, tracked=candidate.tracked, reviewed=True,
            sha256=sha256(data) if data is not None else None,
            git_blob=git_blob(root, candidate.path, data) if data is not None else None,
            added=added, removed=removed,
        )
        files.append(item)
        chunks.append((item, diff))
        total = sum(len(text) for _, text in chunks)
        if total > max_total_chars:
            # Stop early: a large accidental selection should not diff every remaining file.
            largest = sorted(chunks, key=lambda pair: len(pair[1]), reverse=True)[:5]
            raise ChangeError(
                f"The selected diff has at least {total:,} characters, above the {max_total_chars:,} limit. "
                "Select fewer files with --path or raise --max-total-chars.",
                [f"{entry.path}: {len(text):,} characters" for entry, text in largest],
            )

    output_parts: list[str] = []
    offset = 0
    for item, diff in chunks:
        item.diff_start, item.diff_end = offset, offset + len(diff)
        output_parts.append(diff)
        offset += len(diff)
    snapshot = ChangeSnapshot(base=base, base_commit=base_commit, head_commit=head_commit(root),
                              context_lines=context_lines, files=files)
    return snapshot, "".join(output_parts)


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def changed_since(root: Path, snapshot: ChangeSnapshot) -> list[tuple[str, str]]:
    """Reviewed paths whose working-tree bytes differ from the snapshot, with how they changed."""
    changes: list[tuple[str, str]] = []
    for item in snapshot.reviewed:
        try:
            current = worktree_digest(root, item.path)
        except SkipFile as exc:
            changes.append((item.path, str(exc)))
            continue
        if current == item.sha256:
            continue
        if current is None:
            changes.append((item.path, "deleted"))
        elif item.sha256 is None:
            changes.append((item.path, "re-created"))
        else:
            changes.append((item.path, "modified"))
    return changes


def matches_commit(root: Path, snapshot: ChangeSnapshot, commit: str) -> bool:
    """True when every reviewed path has exactly the reviewed blob (or is absent) in the commit."""
    paths = [item.path for item in snapshot.reviewed]
    if not paths or any(item.sha256 is not None and item.git_blob is None for item in snapshot.reviewed):
        return False
    result = _run_git(root, "ls-tree", "-z", commit, "--", *paths)
    if result.returncode != 0:
        return False
    blobs: dict[str, str] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"\t")
        parts = meta.decode("ascii").split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[raw_path.decode("utf-8", "replace")] = parts[2]
    return all(blobs.get(item.path) == item.git_blob for item in snapshot.reviewed)
