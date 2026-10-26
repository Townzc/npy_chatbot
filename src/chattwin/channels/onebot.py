"""OneBot v11 forward WebSocket. API echo correlates requests, not idempotency.

Only read-only probe is enabled by default. User-run live mode requires explicit
allow_send and immutable account/recipient IDs. No bridge is bundled.
"""

import asyncio
import json
from urllib.parse import urlparse

from websockets.asyncio.client import ClientConnection, connect

from chattwin.domain import ChannelCapabilities, DomainError, SendReceipt, SendRequest, uid


class OneBotAdapter:
    def __init__(self, url: str, account_id: str, token: str = "", *, allow_send: bool = False):
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or parsed.username or parsed.password or parsed.query:
            raise ValueError("Use ws(s) URL without inline credentials/query; token is separate")
        if parsed.scheme == "ws" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote bridge requires wss")
        self.url, self.account_id, self.token, self.allow_send = (
            url,
            str(account_id),
            token,
            allow_send,
        )
        self.pending: dict[str, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.ws: ClientConnection | None = None
        self.reader: asyncio.Task | None = None
        self.verified = False
        self.version = "unverified"
        self.allowed_recipients: set[str] = set()

    def capabilities(self):
        return ChannelCapabilities(
            receive_private=True,
            send_text=True,
            stable_message_id=True,
            tested_version=self.version,
        )

    async def open(self):
        self.ws = await connect(
            self.url,
            additional_headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            max_size=1024 * 1024,
            open_timeout=5,
        )
        self.reader = asyncio.create_task(self._read())
        try:
            identity = await self.call("get_login_info", {})
            if str(identity.get("user_id")) != self.account_id:
                raise DomainError(
                    "ACCOUNT_MISMATCH", "Bridge login identity does not match configured account"
                )
            self.verified = True
            version = await self.call("get_version_info", {})
            self.version = (
                str(version.get("app_name", "unknown"))
                + ":"
                + str(version.get("app_version", "unknown"))
            )
        except BaseException:
            await self.close()
            raise
        return {
            "identity_verified": True,
            "bridge_version": self.version,
            "send_enabled": self.allow_send,
            "real_conversation_verified": False,
        }

    async def _read(self):
        assert self.ws is not None
        try:
            async for raw in self.ws:
                obj = json.loads(raw)
                echo = obj.get("echo")
                if echo is not None:
                    future = self.pending.get(str(echo))
                    if future and not future.done():
                        future.set_result(obj)
                elif (
                    str(obj.get("self_id")) == self.account_id
                    and obj.get("message_type") == "private"
                ):
                    # Unselected bodies are never persisted/queued. Probe selects nobody.
                    sender = str(obj.get("user_id"))
                    target = str(obj.get("target_id", sender))
                    if sender in self.allowed_recipients or target in self.allowed_recipients:
                        self.events.put_nowait(obj)
        except Exception:
            pass
        finally:
            self.verified = False
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("bridge disconnected"))

    async def _begin(self, action: str, params: dict):
        if self.ws is None:
            raise ConnectionError("bridge is not connected")
        echo = uid()
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
        except BaseException:
            self.pending.pop(echo, None)
            raise
        future.add_done_callback(lambda _: self.pending.pop(echo, None))
        return future

    async def call(self, action: str, params: dict):
        if action not in ("get_login_info", "get_version_info", "get_status", "get_msg"):
            raise ValueError("Control calls are read-only; sends must use the outbox")
        response = await asyncio.wait_for(await self._begin(action, params), 5)
        if response.get("status") != "ok" or response.get("retcode") != 0:
            raise DomainError("BRIDGE_REJECTED", "Bridge rejected read-only API request", 503)
        return response.get("data", {})

    async def send_text(self, request: SendRequest) -> asyncio.Future[SendReceipt]:
        if (
            not self.allow_send
            or not self.verified
            or request.binding.channel_account_id != self.account_id
            or request.binding.recipient_id not in self.allowed_recipients
        ):
            future = asyncio.get_running_loop().create_future()
            future.set_result(
                SendReceipt(status="rejected", detail="Sending disabled or binding unverified")
            )
            return future
        response = await self._begin(
            "send_private_msg",
            {
                "user_id": int(request.binding.recipient_id),
                "message": [{"type": "text", "data": {"text": request.text}}],
            },
        )

        async def receipt():
            try:
                obj = await asyncio.wait_for(response, 15)
                if (
                    obj.get("status") == "ok"
                    and obj.get("retcode") == 0
                    and obj.get("data", {}).get("message_id") is not None
                ):
                    return SendReceipt(
                        status="confirmed", platform_message_id=str(obj["data"]["message_id"])
                    )
                if obj.get("status") == "failed":
                    return SendReceipt(status="rejected", detail="bridge rejected request")
            except Exception:
                pass
            return SendReceipt(
                status="unknown", detail="No definitive platform receipt; not retried"
            )

        return asyncio.create_task(receipt())

    async def receive(self):
        while self.verified:
            yield await self.events.get()

    async def reconcile(self, outbox_id: str):
        return SendReceipt(
            status="unknown", detail="OneBot has no standard lookup by client request ID"
        )

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            await self.reader
        self.verified = False
