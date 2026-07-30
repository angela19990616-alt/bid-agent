from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request

from app.config.settings import settings


INVITE_COOKIE = "bid_agent_invite_access"


class InviteAccessService:
    @staticmethod
    def verify_code(code: str) -> bool:
        configured = settings.invite_code
        return bool(configured) and hmac.compare_digest(
            code.strip(),
            configured,
        )

    @classmethod
    def issue_token(cls) -> str:
        expires_at = int(
            time.time() + settings.invite_access_ttl_hours * 3600
        )
        signature = cls._signature(expires_at)
        return f"v1.{expires_at}.{signature}"

    @classmethod
    def authorize(cls, request: Request) -> bool:
        token = request.cookies.get(INVITE_COOKIE, "")
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            return False
        try:
            expires_at = int(parts[1])
        except ValueError:
            return False
        if expires_at <= int(time.time()):
            return False
        return hmac.compare_digest(
            parts[2],
            cls._signature(expires_at),
        )

    @staticmethod
    def _signature(expires_at: int) -> str:
        secret = (
            f"{settings.edge_proxy_secret}:{settings.invite_code}"
        ).encode("utf-8")
        return hmac.new(
            secret,
            f"invite-access:{expires_at}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
