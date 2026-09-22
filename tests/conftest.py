"""Offline test defaults: test runs must never send live messages."""

import os
import socket

import httpx
import pytest
import requests

os.environ["ENVIRONMENT"] = "test"
os.environ["SCHEDULER_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def offline_tests(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6} and address[0] not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise AssertionError(
                "Network access is disabled in tests. Mock the external operation."
            )
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)

    def reject_http(*args, **kwargs):
        raise AssertionError("Live HTTP is disabled in tests. Use a mock transport.")

    async def reject_async_http(*args, **kwargs):
        reject_http()

    # Windows event loops may need loopback sockets. Block live HTTP explicitly,
    # including local proxies, while allowing in-process TestClient transports.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_http)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", reject_async_http
    )
    monkeypatch.setattr(requests.Session, "send", reject_http)
