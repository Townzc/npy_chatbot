"""Single-account writer, durable mode intents, and a transport-start stop barrier."""

import asyncio
import hashlib
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from sqlalchemy import select

from chattwin.channels import ChannelAdapter
from chattwin.control import transition
from chattwin.domain import (
    Binding,
    Candidate,
    DomainError,
    Mode,
    ModeCommand,
    SendReceipt,
    SendRequest,
    now,
    uid,
)
from chattwin.storage import Store, bindings, inbound, outbox, relationships, sessions, transitions


class Coordinator:
    def __init__(self, store: Store, channel: ChannelAdapter):
        self.store, self.channel = store, channel
        lock_name = hashlib.sha256(channel.account_id.encode()).hexdigest()[:24]
        lock_root = (
            store.root
            if channel.__class__.__name__ == "FakeChannel"
            else Path.home() / ".cache" / "chattwin" / "account-locks"
        )
        lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.process_lock = FileLock(lock_root / (lock_name + ".sender.lock"))
        try:
            self.process_lock.acquire(timeout=0)
        except Timeout as exc:
            raise DomainError(
                "SENDER_ALREADY_RUNNING", "This account already has a sender"
            ) from exc
        self.gate = asyncio.Lock()
        self.draining = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.before_start = None  # fault-injection hook, runs outside the final barrier
        self.next_send_at = 0.0
        self.recover()

    def recover(self):
        with self.store.transaction() as conn:
            ids = select(bindings.c.id).where(
                bindings.c.channel_account_id == self.channel.account_id
            )
            conn.execute(
                outbox.update()
                .where(outbox.c.binding_id.in_(ids), outbox.c.status == "submitting")
                .values(status="unknown")
            )
            conn.execute(
                outbox.update()
                .where(
                    outbox.c.binding_id.in_(ids),
                    outbox.c.status == "planned",
                    outbox.c.kind.in_(["ai_reply", "enable_notice"]),
                )
                .values(status="cancelled")
            )
            conn.execute(
                sessions.update()
                .where(sessions.c.binding_id.in_(ids), sessions.c.mode != "HUMAN")
                .values(mode="PAUSED", control_epoch=sessions.c.control_epoch + 1)
            )
            for row in (
                conn.execute(select(sessions).where(sessions.c.binding_id.in_(ids)))
                .mappings()
                .all()
            ):
                payload = dict(row["payload"])
                payload["scope_updates"] = 0
                conn.execute(
                    sessions.update()
                    .where(sessions.c.binding_id == row["binding_id"])
                    .values(payload=payload)
                )

    def create_binding(self, binding: Binding):
        if binding.channel_account_id != self.channel.account_id:
            raise DomainError("ACCOUNT_MISMATCH", "Verified account does not match binding")
        with self.store.transaction() as conn:
            scope = conn.execute(
                select(relationships.c.id).where(
                    relationships.c.id == binding.relationship_id,
                    relationships.c.persona_id == binding.persona_id,
                )
            ).first()
            if not scope:
                raise DomainError(
                    "SCOPE_MISMATCH", "Relationship does not belong to this Persona", 403
                )
            if conn.execute(select(bindings).where(bindings.c.id == binding.id)).first():
                existing = conn.execute(
                    select(bindings.c.payload).where(bindings.c.id == binding.id)
                ).scalar_one()
                if existing != binding.model_dump():
                    raise DomainError("IMMUTABLE_BINDING", "Create a new binding instead")
                return
            conn.execute(
                bindings.insert().values(
                    id=binding.id,
                    persona_id=binding.persona_id,
                    relationship_id=binding.relationship_id,
                    channel_account_id=binding.channel_account_id,
                    conversation_id=binding.conversation_id,
                    payload=binding.model_dump(),
                    active=True,
                )
            )
            conn.execute(
                sessions.insert().values(
                    binding_id=binding.id,
                    mode="HUMAN",
                    control_epoch=0,
                    context_seq=0,
                    payload={
                        "persona_version": 1,
                        "memory_version": 1,
                        "model_deployment_id": "mock-v1",
                    },
                )
            )

    def _binding(self, conn, binding_id: str) -> Binding:
        row = (
            conn.execute(
                select(bindings).where(bindings.c.id == binding_id, bindings.c.active.is_(True))
            )
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("BINDING_NOT_FOUND", "Binding not found or archived", 404)
        binding = Binding.model_validate(row["payload"])
        if binding.channel_account_id != self.channel.account_id:
            raise DomainError("ACCOUNT_MISMATCH", "Binding belongs to another account", 403)
        return binding

    def status(self, binding_id: str) -> dict[str, Any]:
        with self.store.engine.connect() as conn:
            self._binding(conn, binding_id)
            row = dict(
                conn.execute(select(sessions).where(sessions.c.binding_id == binding_id))
                .mappings()
                .one()
            )
            notices = (
                conn.execute(
                    select(outbox)
                    .where(outbox.c.binding_id == binding_id)
                    .order_by(outbox.c.created_at)
                )
                .mappings()
                .all()
            )
            row["notifications"] = [
                {
                    "id": n["id"],
                    "kind": n["kind"],
                    "status": n["status"],
                    "text": n["payload"]["text"],
                }
                for n in notices
                if n["kind"] != "ai_reply"
            ]
            row["in_flight"] = [
                n["id"] for n in notices if n["status"] in ("submitting", "unknown")
            ]
            row["ai_stopped"] = row["mode"] != "AI_ACTIVE"
            return row

    async def command(self, binding_id: str, command: ModeCommand):
        async with self.gate:
            with self.store.transaction() as conn:
                self._binding(conn, binding_id)
                old_command = (
                    conn.execute(
                        select(transitions).where(transitions.c.command_id == command.command_id)
                    )
                    .mappings()
                    .first()
                )
                if old_command:
                    if (
                        old_command["binding_id"] != binding_id
                        or old_command["payload"]["action"] != command.action
                    ):
                        raise DomainError(
                            "COMMAND_CONFLICT", "command_id was used for a different operation"
                        )
                else:
                    session = (
                        conn.execute(select(sessions).where(sessions.c.binding_id == binding_id))
                        .mappings()
                        .one()
                    )
                    mode = Mode(session["mode"])
                    if command.action == "enable":
                        if command.expected_control_epoch != session["control_epoch"]:
                            raise DomainError("STALE_EPOCH", "Refresh before enabling AI")
                        pending = conn.execute(
                            select(outbox.c.id).where(
                                outbox.c.binding_id == binding_id,
                                outbox.c.status.in_(["planned", "submitting", "unknown"]),
                            )
                        ).first()
                        if pending and mode != Mode.AI_ACTIVE:
                            raise DomainError(
                                "UNRESOLVED_SEND",
                                "Resolve pending notifications or unknown sends first",
                            )
                    new_mode, notice = transition(mode, command.action)
                    if (
                        command.action == "pause"
                        and command.expected_control_epoch is not None
                        and command.expected_control_epoch != session["control_epoch"]
                    ):
                        new_mode, notice = mode, None
                    no_op = new_mode == mode
                    epoch = session["control_epoch"] + (0 if no_op else 1)
                    tid = uid()
                    payload = {
                        "action": command.action,
                        "control_epoch": epoch,
                        "created_at": now().isoformat(),
                    }
                    conn.execute(
                        transitions.insert().values(
                            id=tid,
                            command_id=command.command_id,
                            binding_id=binding_id,
                            payload=payload,
                        )
                    )
                    if not no_op:
                        session_payload = dict(session["payload"])
                        session_payload["activated_after_seq"] = (
                            session["context_seq"]
                            if command.action == "enable"
                            else session_payload.get("activated_after_seq", 0)
                        )
                        if command.action == "enable":
                            session_payload["enabled_after_timestamp"] = int(now().timestamp())
                        conn.execute(
                            sessions.update()
                            .where(sessions.c.binding_id == binding_id)
                            .values(
                                mode=new_mode.value, control_epoch=epoch, payload=session_payload
                            )
                        )
                    if command.action != "enable" and not no_op:
                        conn.execute(
                            outbox.update()
                            .where(
                                outbox.c.binding_id == binding_id,
                                outbox.c.status == "planned",
                                outbox.c.kind.in_(["ai_reply", "enable_notice"]),
                            )
                            .values(status="cancelled")
                        )
                    if notice:
                        kind = "enable_notice" if command.action == "enable" else "takeover_notice"
                        conn.execute(
                            outbox.insert().values(
                                id=uid(),
                                binding_id=binding_id,
                                transition_id=tid,
                                kind=kind,
                                status="planned",
                                created_at=now().isoformat(),
                                payload={
                                    "text": notice,
                                    "control_epoch": epoch,
                                    "started_at": None,
                                },
                            )
                        )
        # gate release is the stop barrier: no old request may begin after this response
        return self.status(binding_id)

    async def incoming(
        self, binding_id: str, event_id: str, text: str, *, sender_id: str | None = None
    ) -> bool:
        async with self.gate:
            with self.store.transaction() as conn:
                binding = self._binding(conn, binding_id)
                if sender_id is not None and sender_id != binding.recipient_id:
                    return False  # don't persist unselected people's bodies
                event_key = hashlib.sha256(f"{binding_id}:{event_id}".encode()).hexdigest()
                if conn.execute(select(inbound.c.id).where(inbound.c.id == event_key)).first():
                    return False
                session = (
                    conn.execute(select(sessions).where(sessions.c.binding_id == binding_id))
                    .mappings()
                    .one()
                )
                conn.execute(
                    inbound.insert().values(
                        id=event_key,
                        binding_id=binding_id,
                        payload={
                            "text": text,
                            "occurred_at": now().isoformat(),
                            "control_epoch": session["control_epoch"],
                            "context_seq": session["context_seq"] + 1,
                        },
                    )
                )
                conn.execute(
                    sessions.update()
                    .where(sessions.c.binding_id == binding_id)
                    .values(context_seq=sessions.c.context_seq + 1)
                )
                conn.execute(
                    outbox.update()
                    .where(
                        outbox.c.binding_id == binding_id,
                        outbox.c.kind == "ai_reply",
                        outbox.c.status == "planned",
                    )
                    .values(status="cancelled")
                )
        return True

    async def enqueue(self, candidate: Candidate):
        async with self.gate:
            with self.store.transaction() as conn:
                self._binding(conn, candidate.binding_id)
                session = (
                    conn.execute(
                        select(sessions).where(sessions.c.binding_id == candidate.binding_id)
                    )
                    .mappings()
                    .one()
                )
                if not self._candidate_valid(candidate.model_dump(mode="json"), session):
                    raise DomainError(
                        "STALE_CANDIDATE", "Mode or context changed during generation"
                    )
                conn.execute(
                    outbox.insert().values(
                        id=candidate.id,
                        binding_id=candidate.binding_id,
                        kind="ai_reply",
                        status="planned",
                        created_at=now().isoformat(),
                        payload=candidate.model_dump(mode="json"),
                    )
                )

    def _candidate_valid(self, data, session) -> bool:
        return bool(
            not session["payload"].get("scope_updates", 0)
            and session["mode"] == "AI_ACTIVE"
            and data["control_epoch"] == session["control_epoch"]
            and data["context_seq"] == session["context_seq"]
            and datetime.fromisoformat(data["expires_at"]) > now()
            and all(
                data[k] == session["payload"].get(k)
                for k in ("persona_version", "memory_version", "model_deployment_id")
            )
        )

    @asynccontextmanager
    async def scope_update(self, persona_id: str, relationship_id: str):
        async def bump(delta):
            async with self.gate:
                with self.store.transaction() as conn:
                    ids = select(bindings.c.id).where(
                        bindings.c.persona_id == persona_id,
                        bindings.c.relationship_id == relationship_id,
                    )
                    rows = (
                        conn.execute(select(sessions).where(sessions.c.binding_id.in_(ids)))
                        .mappings()
                        .all()
                    )
                    for row in rows:
                        payload = dict(row["payload"])
                        payload["memory_version"] += 1
                        payload["scope_updates"] = max(0, payload.get("scope_updates", 0) + delta)
                        conn.execute(
                            sessions.update()
                            .where(sessions.c.binding_id == row["binding_id"])
                            .values(payload=payload)
                        )

        await bump(1)
        try:
            yield
        finally:
            await bump(-1)

    async def drain(self):
        async with self.draining:
            rows = self.store.rows(outbox, outbox.c.status == "planned")
            for row in sorted(rows, key=lambda r: r["created_at"]):
                if self.before_start:
                    await self.before_start(row)
                await self._start(row["id"])

    async def _start(self, outbox_id: str):
        async with self.gate:
            with self.store.transaction() as conn:
                row = conn.execute(select(outbox).where(outbox.c.id == outbox_id)).mappings().one()
                if row["status"] != "planned":
                    return
                if time.monotonic() < self.next_send_at:
                    return
                # Other account's work stays untouched.
                b = (
                    conn.execute(select(bindings).where(bindings.c.id == row["binding_id"]))
                    .mappings()
                    .one()
                )
                if b["channel_account_id"] != self.channel.account_id:
                    return
                binding = self._binding(conn, row["binding_id"])
                blocked = conn.execute(
                    select(outbox.c.id).where(
                        outbox.c.binding_id == binding.id,
                        outbox.c.status.in_(["submitting", "unknown"]),
                    )
                ).first()
                if blocked:
                    return
                session = (
                    conn.execute(select(sessions).where(sessions.c.binding_id == binding.id))
                    .mappings()
                    .one()
                )
                payload = dict(row["payload"])
                if row["kind"] == "ai_reply":
                    valid = self._candidate_valid(payload, session)
                else:
                    required = "ENABLING" if row["kind"] == "enable_notice" else "HUMAN"
                    valid = (
                        session["mode"] == required
                        and session["control_epoch"] == payload["control_epoch"]
                    )
                if not valid:
                    conn.execute(
                        outbox.update().where(outbox.c.id == outbox_id).values(status="cancelled")
                    )
                    return
                conn.execute(
                    outbox.update().where(outbox.c.id == outbox_id).values(status="submitting")
                )
                request = SendRequest(
                    outbox_id=outbox_id, binding=binding, kind=row["kind"], text=payload["text"]
                )
            try:
                # Only transport start is protected. Long receipt wait is outside the barrier.
                future = await asyncio.wait_for(self.channel.send_text(request), timeout=2)
                self.next_send_at = time.monotonic() + (1.0 if binding.channel == "onebot" else 0.0)
                with self.store.transaction() as conn:
                    payload["started_at"] = now().isoformat()
                    conn.execute(
                        outbox.update().where(outbox.c.id == outbox_id).values(payload=payload)
                    )
            except Exception:
                future = asyncio.get_running_loop().create_future()
                future.set_result(
                    SendReceipt(status="unknown", detail="transport start failed; do not retry")
                )
            task = asyncio.create_task(self._receipt(outbox_id, future))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _receipt(self, outbox_id: str, future):
        try:
            receipt = await asyncio.wait_for(asyncio.shield(future), timeout=20)
        except (Exception, asyncio.CancelledError):
            receipt = SendReceipt(
                status="unknown", detail="receipt unavailable; reconciliation required"
            )
        async with self.gate:
            with self.store.transaction() as conn:
                row = conn.execute(select(outbox).where(outbox.c.id == outbox_id)).mappings().one()
                payload = dict(row["payload"])
                payload["receipt"] = receipt.model_dump()
                conn.execute(
                    outbox.update()
                    .where(outbox.c.id == outbox_id)
                    .values(status=receipt.status, payload=payload)
                )
                session = (
                    conn.execute(select(sessions).where(sessions.c.binding_id == row["binding_id"]))
                    .mappings()
                    .one()
                )
                valid_epoch = session["control_epoch"] == payload["control_epoch"]
                if row["kind"] == "enable_notice" and valid_epoch and session["mode"] == "ENABLING":
                    conn.execute(
                        sessions.update()
                        .where(sessions.c.binding_id == row["binding_id"])
                        .values(mode="AI_ACTIVE" if receipt.status == "confirmed" else "PAUSED")
                    )
                elif row["kind"] == "ai_reply" and valid_epoch and receipt.status != "confirmed":
                    conn.execute(
                        sessions.update()
                        .where(sessions.c.binding_id == row["binding_id"])
                        .values(mode="PAUSED", control_epoch=session["control_epoch"] + 1)
                    )

    async def settle(self):
        """For deterministic local transports/tests only; live callers poll status."""
        await self.drain()
        if self.tasks:
            await asyncio.gather(*list(self.tasks))

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.process_lock.release()
