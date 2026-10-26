"""Channel transport starts before send_text returns its receipt future.

Only outbox may invoke send_text. The coordinator holds its stop barrier until
this method returns; receipt waiting never holds that barrier.
"""

import asyncio
from typing import Protocol

from chattwin.domain import ChannelCapabilities, SendReceipt, SendRequest, uid


class ChannelAdapter(Protocol):
    account_id: str

    def capabilities(self) -> ChannelCapabilities: ...
    async def send_text(self, request: SendRequest) -> asyncio.Future[SendReceipt]: ...
    async def reconcile(self, outbox_id: str) -> SendReceipt: ...


class FakeChannel:
    """Explicit synthetic transport. Never connects to a real messaging service."""

    def __init__(self, account_id: str = "synthetic-account", auto_confirm: bool = True):
        self.account_id = account_id
        self.auto_confirm = auto_confirm
        self.started: list[SendRequest] = []
        self.pending: dict[str, asyncio.Future[SendReceipt]] = {}

    def capabilities(self):
        return ChannelCapabilities(
            receive_private=True,
            send_text=True,
            stable_message_id=True,
            tested_version="synthetic-v1",
        )

    async def send_text(self, request: SendRequest) -> asyncio.Future[SendReceipt]:
        self.started.append(request)  # observable transport boundary, no preceding await
        future: asyncio.Future[SendReceipt] = asyncio.get_running_loop().create_future()
        self.pending[request.outbox_id] = future
        if self.auto_confirm:
            future.set_result(SendReceipt(status="confirmed", platform_message_id="fake-" + uid()))
        return future

    async def reconcile(self, outbox_id: str) -> SendReceipt:
        future = self.pending.get(outbox_id)
        if future and future.done() and not future.cancelled():
            return future.result()
        return SendReceipt(status="unknown", detail="synthetic receipt unavailable")
