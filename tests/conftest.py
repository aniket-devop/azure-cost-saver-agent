"""Safety net for the whole suite: automated tests must never reach a real network.

Loopback connections stay allowed (some tests may start a local server); everything else raises.
"""

import ipaddress
import socket

import pytest

_REAL_CONNECT = socket.socket.connect


def _is_loopback(address: object) -> bool:
    if isinstance(address, str):  # AF_UNIX path
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def guarded_connect(self, address):
        if not _is_loopback(address):
            raise AssertionError(f"test tried to open a network connection to {address!r}")
        return _REAL_CONNECT(self, address)

    def no_dns(host, *args, **kwargs):
        if host in ("localhost", "127.0.0.1", "::1"):
            return socket._socket.getaddrinfo(host, *args, **kwargs)
        raise AssertionError(f"test tried to resolve host {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
