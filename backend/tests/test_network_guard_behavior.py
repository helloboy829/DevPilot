import asyncio
import socket

import pytest
from test_network_guard import install_network_guard


def test_guard_allows_loopback_socketpair_but_blocks_network(monkeypatch):
    install_network_guard(monkeypatch)

    # Windows SelectorEventLoop creates an internal TCP socketpair on loop init.
    asyncio.run(asyncio.sleep(0))
    addresses = socket.getaddrinfo("127.0.0.1", 443, type=socket.SOCK_STREAM)
    assert addresses and all(item[4] for item in addresses)
    with pytest.raises(AssertionError, match="network is forbidden"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(AssertionError, match="network is forbidden"):
        with socket.socket() as sock:
            sock.connect(("203.0.113.7", 443))
