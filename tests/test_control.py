import asyncio
from datetime import timedelta

import pytest

from chattwin.channels import FakeChannel
from chattwin.control import ENABLE_NOTICE, TAKEOVER_NOTICE, transition
from chattwin.domain import Binding, Candidate, DomainError, Mode, ModeCommand, SendReceipt, now
from chattwin.outbox import Coordinator
from chattwin.storage import Store, outbox, personas, relationships


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path)
    store.migrate()
    store.migrate()
    with store.transaction() as conn:
        conn.execute(personas.insert().values(id="p", payload={"name": "虚构"}))
        conn.execute(
            relationships.insert().values(id="r", persona_id="p", payload={"name": "虚构关系"})
        )
    channel = FakeChannel()
    coordinator = Coordinator(store, channel)
    coordinator.create_binding(
        Binding(
            id="b",
            persona_id="p",
            relationship_id="r",
            channel_account_id=channel.account_id,
            conversation_id="c",
            recipient_id="friend",
        )
    )
    yield store, channel, coordinator
    coordinator.process_lock.release()
    store.close()


def cmd(action, id="cmd", epoch=0):
    return ModeCommand(command_id=id, action=action, expected_control_epoch=epoch)


async def active(c):
    await c.command("b", cmd("enable"))
    await c.settle()


def candidate(c):
    status = c.status("b")
    return Candidate(
        binding_id="b",
        control_epoch=status["control_epoch"],
        context_seq=status["context_seq"],
        text="合成回复",
        expires_at=now() + timedelta(minutes=1),
    )


@pytest.mark.parametrize("mode", list(Mode))
def test_pure_takeover_and_pause(mode):
    assert transition(mode, "takeover")[0] == Mode.HUMAN
    assert transition(mode, "pause") == (Mode.HUMAN if mode == Mode.HUMAN else Mode.PAUSED, None)


async def test_notice_gates_activation(system):
    _, channel, c = system
    channel.auto_confirm = False
    result = await c.command("b", cmd("enable"))
    assert result["mode"] == "ENABLING"
    with pytest.raises(DomainError, match="changed"):
        await c.enqueue(candidate(c))
    await c.drain()
    assert channel.started[0].text == ENABLE_NOTICE
    channel.pending[channel.started[0].outbox_id].set_result(SendReceipt(status="confirmed"))
    await asyncio.gather(*list(c.tasks))
    assert c.status("b")["mode"] == "AI_ACTIVE"


async def test_stale_takeover_stops_and_notifies_once(system):
    store, channel, c = system
    await active(c)
    await c.enqueue(candidate(c))
    result = await c.command("b", cmd("takeover", "stop", epoch=-100))
    assert result["ai_stopped"]
    await c.command("b", cmd("takeover", "stop", epoch=-100))
    await c.command("b", cmd("takeover", "stop-new"))
    await c.settle()
    assert [x.text for x in channel.started] == [ENABLE_NOTICE, TAKEOVER_NOTICE]
    assert len(store.rows(outbox, outbox.c.kind == "takeover_notice")) == 1


async def test_takeover_between_claim_and_transport(system):
    _, channel, c = system
    await active(c)
    await c.enqueue(candidate(c))

    async def takeover(row):
        if row["kind"] == "ai_reply":
            await c.command("b", cmd("takeover", "between"))

    c.before_start = takeover
    await c.settle()
    assert not any(r.kind == "ai_reply" for r in channel.started)
    assert c.status("b")["mode"] == "HUMAN"


async def test_slow_enable_receipt_cannot_reactivate(system):
    _, channel, c = system
    channel.auto_confirm = False
    await c.command("b", cmd("enable"))
    await c.drain()
    await c.command("b", cmd("takeover", "stop"))
    await c.drain()
    assert len(channel.started) == 1
    channel.pending[channel.started[0].outbox_id].set_result(SendReceipt(status="confirmed"))
    await asyncio.gather(*list(c.tasks))
    assert c.status("b")["mode"] == "HUMAN"
    channel.auto_confirm = True
    await c.settle()
    assert channel.started[-1].text == TAKEOVER_NOTICE


@pytest.mark.parametrize("receipt", ["unknown", "rejected"])
async def test_failed_notice_does_not_activate_or_retry(system, receipt):
    _, channel, c = system
    channel.auto_confirm = False
    await c.command("b", cmd("enable"))
    await c.drain()
    channel.pending[channel.started[0].outbox_id].set_result(SendReceipt(status=receipt))
    await asyncio.gather(*list(c.tasks))
    assert c.status("b")["mode"] == "PAUSED"
    await c.drain()
    assert len(channel.started) == 1


async def test_unknown_blocks_opposing_notice(system):
    _, channel, c = system
    channel.auto_confirm = False
    await c.command("b", cmd("enable"))
    await c.drain()
    channel.pending[channel.started[0].outbox_id].set_result(SendReceipt(status="unknown"))
    await asyncio.gather(*list(c.tasks))
    await c.command("b", cmd("takeover", "stop"))
    await c.drain()
    assert c.status("b")["mode"] == "HUMAN"
    assert len(channel.started) == 1
    with pytest.raises(DomainError, match="Resolve"):
        await c.command("b", cmd("enable", "again", c.status("b")["control_epoch"]))


async def test_new_context_invalidates_ai_not_notice(system):
    _, channel, c = system
    await c.command("b", cmd("enable"))
    await c.incoming("b", "1", "hi")
    await c.settle()
    assert channel.started[0].text == ENABLE_NOTICE
    old = candidate(c)
    await c.incoming("b", "2", "new")
    with pytest.raises(DomainError, match="changed"):
        await c.enqueue(old)
    assert not await c.incoming("b", "2", "new")


async def test_enable_requires_fresh_epoch(system):
    _, _, c = system
    with pytest.raises(DomainError, match="Refresh"):
        await c.command("b", cmd("enable", epoch=9))


async def test_command_id_cannot_be_reused_for_different_action(system):
    _, _, c = system
    await c.command("b", cmd("enable"))
    with pytest.raises(DomainError, match="different"):
        await c.command("b", cmd("takeover"))


async def test_restart_does_not_resume(system):
    store, channel, c = system
    await active(c)
    await c.enqueue(candidate(c))
    await c.close()
    restarted = Coordinator(store, channel)
    assert restarted.status("b")["mode"] == "PAUSED"
    await restarted.settle()
    assert len(channel.started) == 1
    await restarted.close()


def test_second_sender_rejected_and_binding_immutable(system):
    store, channel, c = system
    with pytest.raises(DomainError, match="already"):
        Coordinator(store, channel)
    with pytest.raises(DomainError, match="new binding"):
        c.create_binding(
            Binding(
                id="b",
                persona_id="p",
                relationship_id="r",
                channel_account_id=channel.account_id,
                conversation_id="c",
                recipient_id="someone-else",
            )
        )


async def test_pause_is_not_human_takeover(system):
    _, channel, c = system
    await active(c)
    await c.command("b", cmd("pause", "fault"))
    await c.settle()
    assert [x.text for x in channel.started] == [ENABLE_NOTICE]


async def test_unselected_sender_does_not_change_context(system):
    _, _, c = system
    assert not await c.incoming("b", "private", "must not persist", sender_id="other")
    assert c.status("b")["context_seq"] == 0


async def test_scope_mutation_invalidates_old_candidate_without_blocking_takeover(system):
    _, channel, c = system
    await active(c)
    previous = candidate(c)
    async with c.scope_update("p", "r"):
        with pytest.raises(DomainError, match="changed"):
            await c.enqueue(previous)
        stopped = await c.command("b", cmd("takeover", "during-import"))
        assert stopped["ai_stopped"]
    assert c.status("b")["payload"]["scope_updates"] == 0
    await c.settle()
    assert channel.started[-1].text == TAKEOVER_NOTICE


async def test_crashed_submitting_send_recovers_unknown_not_retry(system):
    store, channel, c = system
    channel.auto_confirm = False
    await c.command("b", cmd("enable"))
    await c.drain()
    assert c.status("b")["in_flight"]
    await c.close()
    recovered = Coordinator(store, channel)
    try:
        assert recovered.status("b")["mode"] == "PAUSED"
        assert store.rows(outbox)[0]["status"] == "unknown"
        await recovered.drain()
        assert len(channel.started) == 1
    finally:
        await recovered.close()


def test_private_store_rejects_git_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside"):
        Store(checkout / "nested" / "private")
    assert not (checkout / "nested").exists()
