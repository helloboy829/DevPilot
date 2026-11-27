"""Strict network denial that permits only OS-internal loopback socketpairs."""

from __future__ import annotations

import ipaddress
import socket


def install_network_guard(monkeypatch, *, message="Synthetic test network is forbidden"):
    """Block hostname DNS and external sockets while preserving loopback IPC.

    Windows asyncio selector loops may implement their wakeup socketpair with a
    short-lived TCP connection to 127.0.0.1. Allowing numeric loopback addresses
    keeps that runtime mechanism working without permitting external networking.
    """

    def denied(*args, **kwargs):
        raise AssertionError(message)

    def host_from_address(method, args, kwargs):
        address = kwargs.get("address", kwargs.get("address_tuple"))
        if address is None:
            index = 1 if method == "sendto" else 0
            if len(args) > index:
                address = args[index]
        if isinstance(address, tuple) and address:
            return address[0]
        return None

    def guarded(method):
        original = getattr(socket.socket, method)

        def call(sock, *args, **kwargs):
            host = host_from_address(method, args, kwargs)
            try:
                loopback = isinstance(host, str) and ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                return denied(sock, *args, **kwargs)
            return original(sock, *args, **kwargs)

        return call

    original_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        try:
            loopback = isinstance(host, str) and ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            return denied(host, *args, **kwargs)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, guarded(method))
