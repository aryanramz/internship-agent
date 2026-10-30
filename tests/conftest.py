"""Ordinary tests may use loopback services, never external DNS or connections."""
import ipaddress
import os
import socket

import pytest


@pytest.fixture(autouse=True)
def offline_network_boundary(monkeypatch, request):
    if request.node.get_closest_marker("live") and (
        os.environ.get("RUN_LIVE_ATS") == "1" or os.environ.get("RUN_LIVE_SHEETS") == "1"
    ):
        return
    resolve = socket.getaddrinfo
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except (ValueError, TypeError):
            pass
        raise AssertionError("Ordinary tests cannot resolve or connect to external hosts")

    def guarded_resolve(host, *args, **kwargs):
        if host is not None:
            local(host)
        return resolve(host, *args, **kwargs)

    def guarded_connect(self, address):
        if isinstance(address, tuple):
            local(address[0])
        return connect(self, address)

    def guarded_connect_ex(self, address):
        if isinstance(address, tuple):
            local(address[0])
        return connect_ex(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_resolve)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
