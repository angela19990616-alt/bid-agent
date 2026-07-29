from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request

from app.database.db import connect


SESSION_COOKIE = "bid_agent_session"


class WorkspaceAccessDeniedError(Exception):
    pass


@dataclass(frozen=True)
class SessionAccess:
    token: str
    client_ip: str
    is_new: bool


class WorkspaceAccessService:
    @staticmethod
    def session(request: Request) -> SessionAccess:
        existing = request.cookies.get(SESSION_COOKIE)
        token = (
            existing
            if existing and len(existing) >= 32
            else secrets.token_urlsafe(32)
        )
        return SessionAccess(
            token=token,
            client_ip=_client_ip(request),
            is_new=token != existing,
        )

    @classmethod
    def bind(
        cls,
        workspace_id: UUID,
        access: SessionAccess,
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE projects
                    SET access_token_hash = %s,
                        client_ip_hash = %s,
                        access_bound_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        cls.token_hash(access.token),
                        cls.ip_hash(access.token, access.client_ip),
                        workspace_id,
                    ),
                )

    @classmethod
    def authorize(
        cls,
        workspace_id: UUID,
        request: Request,
    ) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or len(token) < 32:
            raise WorkspaceAccessDeniedError
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT access_token_hash, client_ip_hash
                    FROM projects WHERE id = %s
                    """,
                    (workspace_id,),
                )
                row = cursor.fetchone()
        if row is None or not row[0] or not row[1]:
            raise WorkspaceAccessDeniedError
        expected_token = cls.token_hash(token)
        expected_ip = cls.ip_hash(token, _client_ip(request))
        if not hmac.compare_digest(row[0], expected_token):
            raise WorkspaceAccessDeniedError
        if not hmac.compare_digest(row[1], expected_ip):
            raise WorkspaceAccessDeniedError

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def ip_hash(token: str, client_ip: str) -> str:
        return hmac.new(
            token.encode("utf-8"),
            client_ip.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def _client_ip(request: Request) -> str:
    # Nginx replaces X-Real-IP with the TCP peer address. Do not trust a
    # client-supplied X-Forwarded-For chain.
    value = request.headers.get("x-real-ip")
    if value:
        return value.strip()
    return request.client.host if request.client else "unknown"
