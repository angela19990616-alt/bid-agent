from uuid import uuid4

import pytest
from fastapi import Request

from app.services.workspace_access_service import (
    SESSION_COOKIE,
    WorkspaceAccessDeniedError,
    WorkspaceAccessService,
)


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        return None

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return FakeCursor(self.row)


def request(token: str | None, ip: str) -> Request:
    cookie = (
        [(b"cookie", f"{SESSION_COOKIE}={token}".encode())]
        if token
        else []
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-real-ip", ip.encode()), *cookie],
            "client": ("172.18.0.3", 1234),
            "scheme": "http",
            "server": ("test", 80),
            "query_string": b"",
        }
    )


def test_same_session_and_ip_can_access_workspace(monkeypatch):
    token = "a" * 43
    row = (
        WorkspaceAccessService.token_hash(token),
        WorkspaceAccessService.ip_hash(token, "203.0.113.10"),
    )
    monkeypatch.setattr(
        "app.services.workspace_access_service.connect",
        lambda: FakeConnection(row),
    )

    WorkspaceAccessService.authorize(
        uuid4(), request(token, "203.0.113.10")
    )


def test_different_ip_cannot_reuse_workspace_cookie(monkeypatch):
    token = "b" * 43
    row = (
        WorkspaceAccessService.token_hash(token),
        WorkspaceAccessService.ip_hash(token, "203.0.113.10"),
    )
    monkeypatch.setattr(
        "app.services.workspace_access_service.connect",
        lambda: FakeConnection(row),
    )

    with pytest.raises(WorkspaceAccessDeniedError):
        WorkspaceAccessService.authorize(
            uuid4(), request(token, "198.51.100.22")
        )


def test_missing_session_cookie_is_denied():
    with pytest.raises(WorkspaceAccessDeniedError):
        WorkspaceAccessService.authorize(
            uuid4(), request(None, "203.0.113.10")
        )


def test_ip_hash_is_session_keyed_and_not_plain_ip():
    first = WorkspaceAccessService.ip_hash("a" * 43, "203.0.113.10")
    second = WorkspaceAccessService.ip_hash("b" * 43, "203.0.113.10")

    assert first != second
    assert "203.0.113.10" not in first
