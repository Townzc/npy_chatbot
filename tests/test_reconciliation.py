"""Uncertain-send recovery uses synthetic transport evidence only, never real QQ."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from chattwin.api.control_routes import control_router
from chattwin.channels import FakeChannel
from chattwin.domain import Binding, Candidate, DomainError, ModeCommand, SendReceipt, now
from chattwin.importers import DataService
from chattwin.outbox import Coordinator
from chattwin.storage import Store, audit, bindings, outbox


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    data = DataService(store)
    persona = data.create_persona("核对测试虚构本人")
    relation = data.create_relationship(persona["id"], "核对测试虚构好友")
    channel = FakeChannel()
    coordinator = Coordinator(store, channel)
    binding = Binding(
        id="reconciliation-binding",
        persona_id=persona["id"],
        relationship_id=relation["id"],
        channel_account_id=channel.account_id,
        conversation_id="synthetic-reconciliation",
        recipient_id="synthetic-friend",
    )
    coordinator.create_binding(binding)
    yield store, channel, coordinator, binding
    coordinator.process_lock.release()
    store.close()


async def unknown_enable(channel, coordinator, binding):
    channel.auto_confirm = False
    await coordinator.command(
        binding.id, ModeCommand(command_id="enable", action="enable", expected_control_epoch=0)
    )
    await coordinator.drain()
    record = channel.started[-1]
    channel.pending[record.outbox_id].set_result(
        SendReceipt(status="unknown", detail="synthetic uncertain receipt")
    )
    await asyncio.gather(*list(coordinator.tasks))
    return record.outbox_id


async def test_owner_not_sent_is_audited_idempotent_and_never_auto_retried(system):
    store, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    status = coordinator.status(binding.id)
    kwargs = {
        "outcome": "not_sent",
        "evidence": "虚构测试：已核对原窗口且请求已终止，确认没有发送",
        "expected_control_epoch": status["control_epoch"],
    }
    result = await coordinator.resolve_unknown(binding.id, id, **kwargs)
    assert result["item"]["status"] == "rejected"
    assert result["item"]["resolution"]["source"] == "owner_attested"
    assert result["status"]["mode"] == "PAUSED"
    await coordinator.resolve_unknown(binding.id, id, **kwargs)
    assert len(store.rows(audit, audit.c.kind == "outbox_resolution")) == 1
    channel.auto_confirm = True
    await coordinator.settle()
    assert len(channel.started) == 1
    await coordinator.command(
        binding.id,
        ModeCommand(
            command_id="new-explicit-enable",
            action="enable",
            expected_control_epoch=result["status"]["control_epoch"],
        ),
    )
    await coordinator.settle()
    assert len(channel.started) == 2
    assert channel.started[-1].outbox_id != id
    assert coordinator.status(binding.id)["mode"] == "AI_ACTIVE"
    await coordinator.close()


async def test_owner_sent_for_old_enable_cannot_override_takeover(system):
    _, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    stopped = await coordinator.command(
        binding.id, ModeCommand(command_id="stop", action="takeover")
    )
    result = await coordinator.resolve_unknown(
        binding.id,
        id,
        outcome="sent",
        platform_message_id="synthetic-platform-1",
        evidence="虚构测试：已在原窗口确认这条开启通知存在",
        expected_control_epoch=stopped["control_epoch"],
    )
    assert result["status"]["mode"] == "HUMAN"
    channel.auto_confirm = True
    await coordinator.settle()
    assert [item.text for item in channel.started] == ["对方已切换为ai模式", "本人已接管"]
    late = asyncio.get_running_loop().create_future()
    late.set_result(SendReceipt(status="confirmed", platform_message_id="synthetic-platform-1"))
    await coordinator._receipt(id, late)
    assert coordinator.status(binding.id)["mode"] == "HUMAN"
    await coordinator.close()


async def test_unknown_ai_resolution_stays_paused(system):
    _, channel, coordinator, binding = system
    await coordinator.command(
        binding.id, ModeCommand(command_id="enable", action="enable", expected_control_epoch=0)
    )
    await coordinator.settle()
    status = coordinator.status(binding.id)
    candidate = Candidate(
        binding_id=binding.id,
        control_epoch=status["control_epoch"],
        context_seq=status["context_seq"],
        text="虚构AI候选",
        expires_at=now() + timedelta(minutes=1),
    )
    await coordinator.enqueue(candidate)
    channel.auto_confirm = False
    await coordinator.drain()
    channel.pending[candidate.id].set_result(SendReceipt(status="unknown"))
    await asyncio.gather(*list(coordinator.tasks))
    epoch = coordinator.status(binding.id)["control_epoch"]
    resolved = await coordinator.resolve_unknown(
        binding.id,
        candidate.id,
        outcome="sent",
        evidence="虚构测试：原窗口中这条回复已成功显示",
        expected_control_epoch=epoch,
    )
    assert resolved["status"]["mode"] == "PAUSED"
    await coordinator.drain()
    assert len(channel.started) == 2
    await coordinator.close()


async def test_read_only_reconciliation_unknown_then_reliable_receipt(system):
    store, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    unknown = await coordinator.reconcile_unknown(binding.id, id)
    assert not unknown["resolved"] and unknown["item"]["status"] == "unknown"
    assert len(channel.started) == 1
    future = asyncio.get_running_loop().create_future()
    future.set_result(SendReceipt(status="confirmed", platform_message_id="fake-reconciled"))
    channel.pending[id] = future
    resolved = await coordinator.reconcile_unknown(binding.id, id)
    assert resolved["resolved"] and resolved["status"]["mode"] == "PAUSED"
    assert resolved["item"]["resolution"]["source"] == "channel_reconcile"
    assert len(store.rows(audit, audit.c.kind == "outbox_reconcile_attempt")) == 2
    assert len(channel.started) == 1
    await coordinator.close()


async def test_late_conflicting_receipt_reopens_unknown_and_stops_new_session(system):
    store, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    resolved = await coordinator.resolve_unknown(
        binding.id,
        id,
        outcome="not_sent",
        evidence="虚构测试：本人先前核对判定未发送",
        expected_control_epoch=coordinator.status(binding.id)["control_epoch"],
    )
    channel.auto_confirm = True
    await coordinator.command(
        binding.id,
        ModeCommand(
            command_id="new-enable",
            action="enable",
            expected_control_epoch=resolved["status"]["control_epoch"],
        ),
    )
    await coordinator.settle()
    assert coordinator.status(binding.id)["mode"] == "AI_ACTIVE"
    late = asyncio.get_running_loop().create_future()
    late.set_result(SendReceipt(status="confirmed", platform_message_id="fake-late"))
    await coordinator._receipt(id, late)
    assert coordinator.status(binding.id)["mode"] == "PAUSED"
    assert store.rows(outbox, outbox.c.id == id)[0]["status"] == "unknown"
    assert coordinator.unresolved(binding.id)["items"][0]["id"] == id
    await coordinator.close()


async def test_resolution_rejects_wrong_scope_account_archived_and_stale_epoch(system):
    store, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    other_binding = binding.model_copy(
        update={"id": "other-binding", "conversation_id": "other-conversation"}
    )
    coordinator.create_binding(other_binding)
    with pytest.raises(DomainError, match="does not belong"):
        await coordinator.resolve_unknown(
            other_binding.id,
            id,
            outcome="sent",
            evidence="虚构测试：不可跨会话核对发送",
            expected_control_epoch=0,
        )
    foreign = Coordinator(store, FakeChannel(account_id="another-synthetic-account"))
    with pytest.raises(DomainError, match="another account"):
        foreign.unresolved(binding.id)
    await foreign.close()
    with pytest.raises(DomainError, match="refresh"):
        await coordinator.resolve_unknown(
            binding.id,
            id,
            outcome="sent",
            evidence="虚构测试：过期页面不能扩大发送权限",
            expected_control_epoch=999,
        )
    with store.transaction() as conn:
        conn.execute(bindings.update().where(bindings.c.id == binding.id).values(active=False))
    with pytest.raises(DomainError, match="archived"):
        coordinator.unresolved(binding.id)
    await coordinator.close()


async def test_submitting_cannot_be_manually_classified_before_receipt(system):
    _, channel, coordinator, binding = system
    channel.auto_confirm = False
    await coordinator.command(
        binding.id, ModeCommand(command_id="enable", action="enable", expected_control_epoch=0)
    )
    await coordinator.drain()
    id = channel.started[-1].outbox_id
    with pytest.raises(DomainError, match="Only an unknown"):
        await coordinator.resolve_unknown(
            binding.id,
            id,
            outcome="not_sent",
            evidence="虚构测试：超时猜测不能替代传输结果",
            expected_control_epoch=1,
        )
    channel.pending[id].set_result(SendReceipt(status="unknown"))
    await asyncio.gather(*list(coordinator.tasks))
    await coordinator.close()


async def test_takeover_is_not_blocked_by_read_only_reconciliation(system):
    _, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_reconcile(outbox_id):
        entered.set()
        await release.wait()
        return SendReceipt(status="confirmed", platform_message_id="fake-later")

    channel.reconcile = delayed_reconcile
    query = asyncio.create_task(coordinator.reconcile_unknown(binding.id, id))
    await entered.wait()
    stopped = await asyncio.wait_for(
        coordinator.command(
            binding.id, ModeCommand(command_id="stop-during-query", action="takeover")
        ),
        timeout=0.1,
    )
    assert stopped["mode"] == "HUMAN"
    release.set()
    result = await query
    assert result["status"]["mode"] == "HUMAN"
    await coordinator.close()


def test_control_router_auth_and_observation_contract(system):
    store, channel, coordinator, binding = system
    # Persist an uncertain recovery row, without starting an external transport.
    with store.transaction() as conn:
        conn.execute(
            outbox.insert().values(
                id="synthetic-unknown",
                binding_id=binding.id,
                kind="ai_reply",
                status="unknown",
                created_at=now().isoformat(),
                payload={
                    "text": "虚构未决回复",
                    "control_epoch": 0,
                    "started_at": now().isoformat(),
                },
            )
        )
    app = FastAPI()

    async def authenticate(authorization: str | None = Header(None)):
        if authorization != "Bearer synthetic-test":
            raise DomainError("UNAUTHENTICATED", "test only", 401)

    @app.exception_handler(DomainError)
    async def failure(request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status)

    app.include_router(control_router(store, lambda: coordinator, authenticate))
    with TestClient(app) as client:
        query = {"binding_id": binding.id}
        assert client.get("/api/v1/outbox/unresolved", params=query).status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-test"
        assert len(client.get("/api/v1/outbox/unresolved", params=query).json()["items"]) == 1
        invalid = {
            **query,
            "outcome": "not_sent",
            "platform_message_id": "contradictory",
            "evidence": "已经人工核对了虚构测试窗口",
            "expected_control_epoch": 0,
        }
        assert (
            client.post("/api/v1/outbox/synthetic-unknown/resolve", json=invalid).status_code == 422
        )
        valid = {**invalid, "platform_message_id": None}
        result = client.post("/api/v1/outbox/synthetic-unknown/resolve", json=valid)
        assert result.status_code == 200, result.text
        assert result.json()["status"]["mode"] == "HUMAN"
        assert channel.started == []


async def test_concurrent_channel_evidence_conflicting_with_owner_reopens_uncertainty(system):
    _, channel, coordinator, binding = system
    id = await unknown_enable(channel, coordinator, binding)
    entered, release = asyncio.Event(), asyncio.Event()

    async def query(outbox_id):
        entered.set()
        await release.wait()
        return SendReceipt(status="confirmed", platform_message_id="fake-authoritative-result")

    channel.reconcile = query
    read = asyncio.create_task(coordinator.reconcile_unknown(binding.id, id))
    await entered.wait()
    resolved = await coordinator.resolve_unknown(
        binding.id,
        id,
        outcome="not_sent",
        evidence="虚构测试：人工核对尚未发现消息",
        expected_control_epoch=coordinator.status(binding.id)["control_epoch"],
    )
    channel.auto_confirm = True
    await coordinator.command(
        binding.id,
        ModeCommand(
            command_id="reenable-before-query-returns",
            action="enable",
            expected_control_epoch=resolved["status"]["control_epoch"],
        ),
    )
    await coordinator.settle()
    release.set()
    result = await read
    assert result["item"]["status"] == "unknown"
    assert result["status"]["mode"] == "PAUSED"
    await coordinator.close()
