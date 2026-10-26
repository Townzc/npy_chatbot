"""Short-lived owner sessions; tokens stay in memory and die on process restart."""

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from datetime import timedelta

from fastapi import APIRouter, Header, Request
from pydantic import Field

from chattwin.domain import Contract, DomainError, now


class SessionResponse(Contract):
    token: str
    expires_at: str
    lifetime_seconds: int


class SessionInput(Contract):
    lifetime_seconds: int = Field(default=3600, ge=60, le=86400)


class OwnerAuth:
    def __init__(self, owner_secret: str, *, require_session=False, clock=time.monotonic):
        self.owner_secret = owner_secret
        self.require_session = require_session
        self.clock = clock
        self.sessions: OrderedDict[str, float] = OrderedDict()
        self.failures: OrderedDict[str, list[float]] = OrderedDict()

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def valid(self, token):
        if not token:
            return False
        if not self.require_session and hmac.compare_digest(
            token.encode(), self.owner_secret.encode()
        ):
            return True
        key = self.digest(token)
        expiry = self.sessions.get(key)
        if expiry is None:
            return False
        if self.clock() >= expiry:
            self.sessions.pop(key, None)
            return False
        return True

    def issue(self, token, peer, lifetime_seconds):
        timestamp = self.clock()
        history = [stamp for stamp in self.failures.get(peer, []) if stamp > timestamp - 60]
        if len(history) >= 5:
            raise DomainError("LOGIN_RATE_LIMIT", "登录失败次数过多，请一分钟后重试。", 429)
        if not token or not hmac.compare_digest(token.encode(), self.owner_secret.encode()):
            self.failures[peer] = history + [timestamp]
            while len(self.failures) > 1000:
                self.failures.popitem(last=False)
            raise DomainError("UNAUTHENTICATED", "本人访问凭证无效", 401)
        self.failures.pop(peer, None)
        for key, expiry in list(self.sessions.items()):
            if timestamp >= expiry:
                self.sessions.pop(key)
        if len(self.sessions) >= 32:
            raise DomainError(
                "SESSION_LIMIT", "已有 32 个访问会话，请先退出旧会话或等待到期。", 429
            )
        session = secrets.token_urlsafe(32)
        self.sessions[self.digest(session)] = timestamp + lifetime_seconds
        return SessionResponse(
            token=session,
            expires_at=(now() + timedelta(seconds=lifetime_seconds)).isoformat(),
            lifetime_seconds=lifetime_seconds,
        )

    def revoke(self, token):
        self.sessions.pop(self.digest(token), None)


def auth_router(auth: OwnerAuth):
    router = APIRouter(prefix="/api/v1/auth", tags=["owner-sessions"])

    def bearer(header):
        return header.removeprefix("Bearer ") if header and header.startswith("Bearer ") else ""

    @router.post("/session", response_model=SessionResponse)
    async def create_session(
        body: SessionInput, request: Request, authorization: str | None = Header(default=None)
    ):
        peer = request.client.host if request.client else "unknown"
        return auth.issue(bearer(authorization), peer, body.lifetime_seconds)

    @router.delete("/session")
    async def revoke_session(authorization: str | None = Header(default=None)):
        auth.revoke(bearer(authorization))
        return {"revoked": True}

    return router
