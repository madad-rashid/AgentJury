import os
import socket

import pytest


@pytest.mark.skipif(os.environ.get("AGENTJURY_LIVE") == "1", reason="Offline guard disabled for explicitly live tests")
def test_suite_blocks_default_model_endpoint_and_external_dns():
    with socket.socket() as sock:
        with pytest.raises(OSError, match="Offline test"):
            sock.connect(("127.0.0.1", 11434))
    with pytest.raises(OSError, match="Offline test"):
        socket.getaddrinfo("openrouter.ai", 443)
