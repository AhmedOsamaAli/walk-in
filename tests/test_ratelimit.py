"""Which client a request counts against: behind the Cloudflare front door, the visitor's address the front door
vouches for with the shared secret; otherwise the address the hosting proxy saw."""
from dataclasses import replace

import pytest
from starlette.requests import Request

from app import ratelimit


def request(headers: dict[str, str], client: str = "10.0.0.9") -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": (client, 5000)})


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(ratelimit, "settings", replace(ratelimit.settings, proxy_secret="front-door-secret"))
    return "front-door-secret"


def test_the_front_door_names_the_visitor_with_the_shared_secret(secret):
    sent = {"x-proxy-secret": secret, "x-client-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.1, 172.68.0.1"}
    assert ratelimit.client_ip(request(sent)) == "203.0.113.7"


def test_without_the_right_secret_the_visitor_cannot_choose_its_address(secret):
    forged = {"x-proxy-secret": "guess", "x-client-ip": "203.0.113.7", "x-forwarded-for": "6.6.6.6, 198.51.100.1"}
    assert ratelimit.client_ip(request(forged)) == "198.51.100.1"
    assert ratelimit.client_ip(request({"x-client-ip": "203.0.113.7"})) == "10.0.0.9"


def test_with_no_secret_set_the_header_means_nothing(monkeypatch):
    monkeypatch.setattr(ratelimit, "settings", replace(ratelimit.settings, proxy_secret=""))
    sent = {"x-proxy-secret": "", "x-client-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.1"}
    assert ratelimit.client_ip(request(sent)) == "198.51.100.1"
