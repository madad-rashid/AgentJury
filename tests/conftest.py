"""Offline tests may contact only HTTP servers created by the test process."""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def offline_network_guard(monkeypatch):
    if os.environ.get("AGENTJURY_LIVE") == "1":
        return
    ports = set()
    bind = socket.socket.bind
    connect = socket.socket.connect
    resolve = socket.getaddrinfo

    def test_bind(sock, address):
        result = bind(sock, address)
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1") and address[1] == 0:
            ports.add(sock.getsockname()[1])
        return result

    def test_connect(sock, address):
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1") and address[1] in ports):
            raise OSError("Offline test blocked an unregistered network endpoint.")
        return connect(sock, address)

    def test_resolve(host, *args, **kwargs):
        if host not in ("localhost", "127.0.0.1", "::1", None):
            raise OSError("Offline test blocked network name resolution.")
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "bind", test_bind)
    monkeypatch.setattr(socket.socket, "connect", test_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", test_connect)
    monkeypatch.setattr(socket, "getaddrinfo", test_resolve)


@pytest.fixture(autouse=True)
def restore_roles():
    """Role registration is global; a test that registers roles must not change other tests' judges."""
    from agentjury.judges import ROLES
    saved = dict(ROLES)
    yield
    ROLES.clear()
    ROLES.update(saved)


class GitRepo:
    """A throwaway repository with exact file bytes and no user or system Git config."""

    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.path, capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    def write(self, name: str, content: bytes | str) -> Path:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return target

    def commit(self, message: str = "commit") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "AgentJury Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")
    path = tmp_path / "repo"
    path.mkdir()
    repo = GitRepo(path)
    repo.git("init", "-q")
    repo.git("config", "core.autocrlf", "false")
    monkeypatch.chdir(path)
    return repo
