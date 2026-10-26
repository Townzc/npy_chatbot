"""Selected private conversation receive loop; every output still uses outbox."""

import asyncio
import time

from chattwin.domain import ModeCommand, uid
from chattwin.storage import outbox


class LiveRuntime:
    def __init__(self, coordinator, engine, binding):
        self.coordinator, self.engine, self.binding = coordinator, engine, binding
        self.channel = coordinator.channel
        self.tasks: list[asyncio.Task] = []
        self.generation: asyncio.Task | None = None
        self.buffer: list[str] = []
        self.event_ids: list[str] = []
        self.seen: set[str] = set()
        self.first_at = 0.0
        self.last_at = 0.0

    def start(self):
        self.tasks = [asyncio.create_task(self.receive()), asyncio.create_task(self.tick())]

    def cancel_generation(self):
        if self.generation:
            self.generation.cancel()
        self.buffer.clear()
        self.event_ids.clear()

    async def pause(self, expected_epoch=None):
        if (
            expected_epoch is not None
            and self.coordinator.status(self.binding.id)["control_epoch"] != expected_epoch
        ):
            return
        self.cancel_generation()
        await self.coordinator.command(
            self.binding.id,
            ModeCommand(command_id=uid(), action="pause", expected_control_epoch=expected_epoch),
        )

    async def receive(self):
        async for event in self.channel.receive():
            sender = str(event.get("user_id"))
            message_id = str(event.get("message_id", ""))
            if sender == self.channel.account_id or event.get("post_type") == "message_sent":
                known = any(
                    r["payload"].get("receipt", {}).get("platform_message_id") == message_id
                    for r in self.coordinator.store.rows(
                        outbox, outbox.c.binding_id == self.binding.id
                    )
                )
                if not known:
                    # Ambiguous self echo pauses; it never impersonates a human takeover.
                    await self.pause()
                continue
            if sender != self.binding.recipient_id or not message_id or message_id in self.seen:
                continue
            self.seen.add(message_id)
            if len(self.seen) > 10000:
                # Durable inbound dedup is the final defense after generation.
                self.seen = {message_id}
            parts = event.get("message", [])
            if not isinstance(parts, list) or any(p.get("type") != "text" for p in parts):
                continue
            text = "".join(str(p.get("data", {}).get("text", "")) for p in parts)
            if text.strip() in {"停止AI", "停止ai", "关闭AI", "别用AI回复"}:
                await self.pause()
                continue
            status = self.coordinator.status(self.binding.id)
            mode = status["mode"]
            if mode not in {"AI_ACTIVE", "ENABLING"}:
                continue
            event_time = event.get("time")
            if (
                not isinstance(event_time, (int, float))
                or event_time
                < max(
                    status["payload"].get("enabled_after_timestamp", time.time()), time.time() - 120
                )
                or event_time > time.time() + 60
            ):
                continue
            if self.generation and not self.generation.done():
                self.generation.cancel()
            # Context invalidation happens immediately, not after debounce.
            accepted = await self.coordinator.incoming(
                self.binding.id, "received:" + message_id, text, sender_id=sender
            )
            if not accepted:
                continue
            if not self.buffer:
                self.first_at = time.monotonic()
            self.last_at = time.monotonic()
            self.buffer.append(text)
            self.event_ids.append(message_id)

    async def generate(self, text, event_id):
        epoch = self.coordinator.status(self.binding.id)["control_epoch"]
        try:
            await self.engine.reply(self.binding.id, text, "B2", event_id, ingest=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            await self.pause(epoch)

    async def tick(self):
        while True:
            await asyncio.sleep(0.2)
            if not self.channel.verified:
                await self.pause()
                return  # explicit reconnect/re-enable; never auto resumes
            await self.coordinator.drain()
            status = self.coordinator.status(self.binding.id)
            if status["mode"] in {"HUMAN", "PAUSED"}:
                self.cancel_generation()
            if (
                self.buffer
                and status["mode"] == "AI_ACTIVE"
                and (time.monotonic() - self.last_at >= 3 or time.monotonic() - self.first_at >= 8)
            ):
                text = "\n".join(self.buffer)[:4000]
                event_id = "batch:" + ":".join(self.event_ids)
                self.buffer, self.event_ids = [], []
                self.generation = asyncio.create_task(self.generate(text, event_id))

    async def close(self):
        self.cancel_generation()
        tasks = self.tasks + ([self.generation] if self.generation else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
