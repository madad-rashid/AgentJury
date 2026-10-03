"""Change discovery, exclusions and snapshot binding against real temporary Git repositories."""

import hashlib
import os
import subprocess

import pytest

from agentjury import change_snapshot
from agentjury.change_snapshot import (
    SECRET_REASON, ChangeError, capture, changed_since, find_candidates, matches_commit, repo_relative,
    repo_root, resolve_commit, secret_named, select,
)


def base_commit(repo):
    return resolve_commit(repo.path, "HEAD")


def snapshot_of(repo, paths=(), **limits):
    commit = base_commit(repo)
    chosen = select(find_candidates(repo.path, commit), list(paths), repo.path, repo.path)
    return capture(repo.path, "HEAD", commit, chosen, **limits)


def by_path(snapshot):
    return {item.path: item for item in snapshot.files}


def test_candidates_cover_tracked_untracked_and_ignored_files(git_repo):
    git_repo.write(".gitignore", "ignored.txt\n")
    git_repo.write("a.py", "a = 1\n")
    git_repo.write("gone.py", "gone = 1\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    (git_repo.path / "gone.py").unlink()
    git_repo.write("new.py", "new = 1\n")
    git_repo.write("staged.py", "staged = 1\n")
    git_repo.git("add", "staged.py")
    git_repo.write("ignored.txt", "never listed\n")
    git_repo.write(".env", "API_KEY=value\n")
    git_repo.write("uv.lock", "lock\n")

    found = {c.path: c for c in find_candidates(git_repo.path, base_commit(git_repo))}

    assert set(found) == {"a.py", "gone.py", "new.py", "staged.py", ".env", "uv.lock"}
    assert (found["a.py"].change, found["a.py"].tracked) == ("modified", True)
    assert found["gone.py"].change == "deleted"
    assert (found["staged.py"].change, found["staged.py"].tracked) == ("added", True)
    assert (found["new.py"].change, found["new.py"].tracked) == ("added", False)
    assert found[".env"].exclusion == SECRET_REASON
    assert found["uv.lock"].exclusion.startswith("lockfile")
    assert found["a.py"].exclusion is None


def test_agentjury_state_is_never_a_candidate(git_repo):
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    git_repo.write(".agentjury/changes/drafts/task.md", "task\n")
    git_repo.write(".agentjury/verdicts/x.json", "{}\n")
    assert find_candidates(git_repo.path, base_commit(git_repo)) == []


@pytest.mark.parametrize("name, secret", [
    (".env", True), (".env.local", True), ("config/.ENV.production", True), (".env.example", False),
    ("deploy/server.pem", True), ("keys/id_ed25519", True), ("id_rsa.pub", True), (".npmrc", True),
    ("infra/prod.tfvars", True), ("home/.ssh/config", True), (".claude/settings.local.json", True),
    (".aws/credentials", True), ("secrets.yaml", True), ("src/secret_santa.py", False),
    ("src/keyboard.py", False), ("README.md", False),
])
def test_secret_named(name, secret):
    assert secret_named(name) is secret


def test_selection_by_file_and_directory_and_refusals(git_repo, tmp_path):
    git_repo.write("src/a.py", "a = 1\n")
    git_repo.write("src/b.py", "b = 1\n")
    git_repo.write("docs/x.md", "x\n")
    git_repo.commit()
    for name in ("src/a.py", "src/b.py", "docs/x.md"):
        git_repo.write(name, "changed\n")
    candidates = find_candidates(git_repo.path, base_commit(git_repo))

    assert [c.path for c in select(candidates, ["src"], git_repo.path, git_repo.path)] == ["src/a.py", "src/b.py"]
    assert [c.path for c in select(candidates, ["docs/x.md"], git_repo.path, git_repo.path)] == ["docs/x.md"]
    assert [c.path for c in select(candidates, ["a.py"], git_repo.path, git_repo.path / "src")] == ["src/a.py"]
    assert len(select(candidates, [], git_repo.path, git_repo.path)) == 3
    with pytest.raises(ChangeError, match="not a changed file"):
        select(candidates, ["README.md"], git_repo.path, git_repo.path)
    with pytest.raises(ChangeError, match="outside the repository"):
        select(candidates, [str(tmp_path / "elsewhere.py")], git_repo.path, git_repo.path)
    with pytest.raises(ChangeError, match="outside the repository"):
        repo_relative("../escape.py", git_repo.path, git_repo.path)


def test_capture_builds_the_diff_and_binds_exact_bytes(git_repo):
    git_repo.write("a.py", "def add(a, b):\n    return a + b\n")
    git_repo.commit()
    git_repo.write("a.py", "def add(a, b):\n    return a - b\n")
    git_repo.write("new.py", "print('hi')\nprint('bye')")

    snapshot, output = snapshot_of(git_repo)
    files = by_path(snapshot)

    assert snapshot.base_commit == base_commit(git_repo) == snapshot.head_commit
    assert all(item.reviewed for item in snapshot.files)
    a, new = files["a.py"], files["new.py"]
    assert a.sha256 == hashlib.sha256((git_repo.path / "a.py").read_bytes()).hexdigest()
    assert a.git_blob == git_repo.git("hash-object", "a.py").strip()
    assert (a.added, a.removed, new.added, new.removed) == (1, 1, 2, 0)
    a_diff, new_diff = output[a.diff_start:a.diff_end], output[new.diff_start:new.diff_end]
    assert "-    return a + b\n+    return a - b\n" in a_diff
    assert new_diff == ("diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n"
                        "@@ -0,0 +1,2 @@\n+print('hi')\n+print('bye')\n\\ No newline at end of file\n")
    assert output == a_diff + new_diff


@pytest.mark.skipif(os.name == "nt", reason="uses /dev/null with git diff --no-index")
@pytest.mark.parametrize("content", ["one line\n", "x", "a\nb\n", "\n", "tabs\tand  spaces\nend"])
def test_untracked_diff_matches_git(git_repo, content):
    git_repo.write("base.txt", "base\n")
    git_repo.commit()
    git_repo.write("new.txt", content)
    snapshot, output = snapshot_of(git_repo)
    real = subprocess.run(["git", "diff", "--no-index", "--no-color", "--", "/dev/null", "new.txt"],
                          cwd=git_repo.path, capture_output=True).stdout.decode()
    expected = "".join(line for line in real.splitlines(keepends=True) if not line.startswith("index "))
    assert output == expected


def test_deleted_and_staged_files_are_reviewed(git_repo):
    git_repo.write("old.py", "x = 1\ny = 2\n")
    git_repo.commit()
    (git_repo.path / "old.py").unlink()
    git_repo.write("staged.py", "z = 3\n")
    git_repo.git("add", "staged.py")

    snapshot, output = snapshot_of(git_repo)
    files = by_path(snapshot)

    assert files["old.py"].reviewed and files["old.py"].sha256 is None and files["old.py"].git_blob is None
    assert (files["old.py"].added, files["old.py"].removed) == (0, 2)
    assert files["staged.py"].change == "added" and files["staged.py"].tracked
    assert "deleted file mode" in output and "+z = 3" in output


def test_secret_named_files_are_never_read(git_repo, monkeypatch):
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    git_repo.write(".env", "OPENAI_API_KEY=do-not-read-me\n")
    git_repo.write("keys/id_rsa", "do-not-read-me\n")
    reads = []
    original = change_snapshot.read_worktree
    monkeypatch.setattr(change_snapshot, "read_worktree",
                        lambda root, path, *limit: reads.append(path) or original(root, path, *limit))

    snapshot, output = snapshot_of(git_repo)
    files = by_path(snapshot)

    assert set(reads) == {"a.py"}
    assert files[".env"].reason == files["keys/id_rsa"].reason == SECRET_REASON
    assert files[".env"].sha256 is None and not files[".env"].reviewed
    assert "do-not-read-me" not in output


def test_binary_lockfile_and_oversize_files_are_omitted(git_repo):
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    git_repo.write("image.bin", b"\x89PNG\x00\x01\x02")
    git_repo.write("latin1.txt", "caf\xe9\n".encode("latin-1"))
    git_repo.write("package-lock.json", "{}\n")
    git_repo.write("big.py", "x = 1\n" * 200)

    snapshot, output = snapshot_of(git_repo, max_file_chars=500)
    files = by_path(snapshot)

    assert files["image.bin"].reason.startswith("binary")
    assert files["latin1.txt"].reason.startswith("not UTF-8")
    assert files["package-lock.json"].reason.startswith("lockfile")
    assert files["big.py"].reason.startswith("diff larger than 500")
    assert [item.path for item in snapshot.reviewed] == ["a.py"]
    assert "x = 1" not in output


def test_symlinks_are_not_followed(git_repo, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("outside-secret-content\n", encoding="utf-8")
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    try:
        os.symlink(secret, git_repo.path / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    snapshot, output = snapshot_of(git_repo)

    assert by_path(snapshot)["link.txt"].reason.startswith("symlink")
    assert "outside-secret-content" not in output


def test_total_cap_refuses_early_with_largest_files(git_repo, monkeypatch):
    git_repo.write("a.py", "a = 1\n")
    git_repo.write("b.py", "b = 1\n")
    git_repo.write("c.py", "c = 1\n")
    git_repo.commit()
    for name in ("a.py", "b.py", "c.py"):
        git_repo.write(name, f"{name} = 2\n" * 15)
    diffs = []
    original = change_snapshot._tracked_diff
    monkeypatch.setattr(change_snapshot, "_tracked_diff",
                        lambda root, base, path, lines: diffs.append(path) or original(root, base, path, lines))
    with pytest.raises(ChangeError, match="above the 400 limit") as refused:
        snapshot_of(git_repo, max_total_chars=400)
    assert diffs == ["a.py", "b.py"]
    assert [detail.split(":")[0] for detail in refused.value.details] == ["a.py", "b.py"]


def test_files_over_the_read_limit_are_omitted_unread(git_repo, monkeypatch):
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    git_repo.write("huge.log", "line\n" * 100)
    monkeypatch.setattr(change_snapshot, "MAX_READ_BYTES", 100)
    snapshot, output = snapshot_of(git_repo)
    assert by_path(snapshot)["huge.log"].reason == "file larger than 100 bytes; not reviewed"
    assert "line" not in output


def test_changed_since_detects_edits_deletion_recreation_and_line_endings(git_repo):
    git_repo.write("a.py", "a = 1\n")
    git_repo.write("old.py", "old\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    (git_repo.path / "old.py").unlink()
    snapshot, _ = snapshot_of(git_repo)
    assert changed_since(git_repo.path, snapshot) == []

    git_repo.write("a.py", "a = 3\n")
    git_repo.write("old.py", "back\n")
    assert changed_since(git_repo.path, snapshot) == [("a.py", "modified"), ("old.py", "re-created")]

    git_repo.write("a.py", "a = 2\r\n")
    (git_repo.path / "old.py").unlink()
    assert changed_since(git_repo.path, snapshot) == [("a.py", "modified")]

    git_repo.write("a.py", "a = 2\n")
    assert changed_since(git_repo.path, snapshot) == []
    (git_repo.path / "a.py").unlink()
    assert changed_since(git_repo.path, snapshot) == [("a.py", "deleted")]


def test_matches_commit_only_for_the_reviewed_content(git_repo):
    git_repo.write("a.py", "a = 1\n")
    git_repo.write("old.py", "old\n")
    git_repo.commit()
    git_repo.write("a.py", "a = 2\n")
    (git_repo.path / "old.py").unlink()
    snapshot, _ = snapshot_of(git_repo)
    assert not matches_commit(git_repo.path, snapshot, snapshot.head_commit)

    head = git_repo.commit("reviewed change")
    assert matches_commit(git_repo.path, snapshot, head)

    git_repo.write("a.py", "a = 3\n")
    later = git_repo.commit("later change")
    assert not matches_commit(git_repo.path, snapshot, later)


def test_repository_and_base_errors(git_repo, tmp_path, monkeypatch):
    with pytest.raises(ChangeError, match="no commits yet"):
        resolve_commit(git_repo.path, "HEAD")
    git_repo.write("a.py", "a = 1\n")
    git_repo.commit()
    with pytest.raises(ChangeError, match="Unknown base"):
        resolve_commit(git_repo.path, "no-such-branch")
    with pytest.raises(ChangeError, match="Invalid base"):
        resolve_commit(git_repo.path, "--output=x")
    outside = tmp_path / "plain"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(ChangeError, match="inside a Git work tree"):
        repo_root(outside)
