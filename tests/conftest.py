"""Offline tests may contact only HTTP servers created by the test process."""

import os
import socket

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
