"""Independent adversarial regressions; all channels here are local and never opened."""

import asyncio
from pathlib import Path

import pytest

from chattwin.channels import FakeChannel
from chattwin.channels.onebot import OneBotAdapter
from chattwin.conversation import ConversationEngine
from chattwin.domain import Binding, DomainError, ModeCommand, uid
from chattwin.importers import DataService
from chattwin.outbox import Coordinator
from chattwin.storage import Store


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path / "runtime")
    store.migrate()
    data = DataService(store)
    persona = data.create_persona("虚构评审本人")
    relation = data.create_relationship(persona["id"], "虚构评审好友")
    channel = FakeChannel()
    coordinator = Coordinator(store, channel)
    coordinator.create_binding(
        Binding(
            id="review-binding",
            persona_id=persona["id"],
            relationship_id=relation["id"],
            channel_account_id=channel.account_id,
            conversation_id="review-conversation",
            recipient_id="synthetic-review-peer",
        )
    )
    yield store, data, channel, coordinator, persona, relation
    coordinator.process_lock.release()
    store.close()


async def test_late_model_failure_preserves_owner_takeover_and_notice(runtime):
    _, data, channel, coordinator, _, _ = runtime
    await coordinator.command(
        "review-binding", ModeCommand(command_id="start", action="enable", expected_control_epoch=0)
    )
    await coordinator.settle()
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedFailure:
        async def generate(self, request):
            entered.set()
            await release.wait()
            raise DomainError("MODEL_UNAVAILABLE", "injected late provider failure", 503)

    engine = ConversationEngine(coordinator, DelayedFailure(), data)
    generation = asyncio.create_task(engine.reply("review-binding", "虚构来信", variant="B0"))
    await entered.wait()
    takeover = await coordinator.command(
        "review-binding",
        ModeCommand(command_id="owner-stop", action="takeover", expected_control_epoch=-1),
    )
    release.set()
    with pytest.raises(DomainError, match="late provider failure"):
        await generation
    current = coordinator.status("review-binding")
    assert current["mode"] == "HUMAN"
    assert current["control_epoch"] == takeover["control_epoch"]
    await coordinator.settle()
    assert [request.text for request in channel.started] == ["对方已切换为ai模式", "本人已接管"]
    await coordinator.close()


async def test_source_revocation_waits_for_http_lease_without_blocking_takeover(runtime):
    """The deferred HTTP transport is synthetic; exercise the real provider boundary."""
    import threading

    import httpx
    from filelock import FileLock, Timeout

    from chattwin.models import HTTPProvider

    store, data, channel, coordinator, persona, relation = runtime
    p, r = persona["id"], relation["id"]
    batch = data.import_file(
        Path(__file__).parents[1] / "examples" / "chatlab_wechat.synthetic.jsonl",
        p,
        r,
        "demo_owner",
        "synthetic-account",
        confirm_human=True,
    )
    data.add_memory(
        p, r, "LEASE_SYNTHETIC_CANARY 展览", [data.list_messages(p, r)[0]["id"]], confirmed=True
    )
    impact = data.deletion_impact(batch["id"], p, r)
    await coordinator.command(
        "review-binding",
        ModeCommand(command_id="source-start", action="enable", expected_control_epoch=0),
    )
    await coordinator.settle()
    entered, release = asyncio.Event(), asyncio.Event()
    attempted = threading.Event()
    observations = []

    class BeforeNetwork:
        async def __aenter__(self):
            entered.set()
            await release.wait()

        async def __aexit__(self, *_):
            pass

    def transport(request):
        # Revocation may only commit after this bounded, already-leased request.
        observations.append(
            (b"LEASE_SYNTHETIC_CANARY" in request.content, bool(data.list_messages(p, r)))
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic reply"}}]})

    provider = HTTPProvider(
        "http://testserver/v1", "synthetic-protocol", "", transport=httpx.MockTransport(transport)
    )
    provider.lock = BeforeNetwork()
    engine = ConversationEngine(coordinator, provider, data)
    generation = asyncio.create_task(engine.reply("review-binding", "展览", variant="B2"))
    deletion = None

    def remove():
        attempted.set()
        return data.delete_import(batch["id"], p, r, impact["impact_hash"])

    try:
        await asyncio.wait_for(entered.wait(), 3)
        with pytest.raises(Timeout):
            FileLock(store.root / "data-management.lock", timeout=0).acquire()
        deletion = asyncio.create_task(asyncio.to_thread(remove))
        assert await asyncio.to_thread(attempted.wait, 3)
        # Takeover must complete even while provider and deletion are waiting.
        taken = await asyncio.wait_for(
            coordinator.command(
                "review-binding", ModeCommand(command_id="source-stop", action="takeover")
            ),
            timeout=1,
        )
        assert taken["mode"] == "HUMAN" and not deletion.done()
        release.set()
        with pytest.raises(DomainError, match="changed during generation"):
            await generation
        await asyncio.wait_for(deletion, 3)
        assert observations == [(True, True)]
        assert data.list_messages(p, r) == []
        assert data.retrieve_memories(p, r, "展览") == []
        await coordinator.settle()
        assert [request.text for request in channel.started] == ["对方已切换为ai模式", "本人已接管"]
    finally:
        release.set()
        await asyncio.gather(generation, *([deletion] if deletion else []), return_exceptions=True)
        await coordinator.close()


def test_core_binding_rejects_relationship_owned_by_other_persona(runtime):
    _, data, channel, coordinator, _, relation = runtime
    other = data.create_persona("另一个虚构档案")
    with pytest.raises(DomainError):
        coordinator.create_binding(
            Binding(
                persona_id=other["id"],
                relationship_id=relation["id"],
                channel_account_id=channel.account_id,
                conversation_id="another-conversation",
                recipient_id="synthetic-peer",
            )
        )


def test_live_account_writer_lock_spans_distinct_data_directories(tmp_path):
    account = "synthetic-lock-review-" + uid()
    first_store, second_store = Store(tmp_path / "one"), Store(tmp_path / "two")
    first_store.migrate()
    second_store.migrate()
    # Construct protocol adapters without calling open(); this makes NO network request.
    first = Coordinator(first_store, OneBotAdapter("ws://127.0.0.1:9", account))
    second = None
    try:
        with pytest.raises(DomainError, match="already"):
            second = Coordinator(second_store, OneBotAdapter("ws://127.0.0.1:9", account))
    finally:
        if second:
            second.process_lock.release()
        first.process_lock.release()
        first_store.close()
        second_store.close()


async def test_live_runtime_durable_duplicate_is_not_rebuffered(runtime):
    from datetime import datetime, timezone

    from chattwin.channels.runtime import LiveRuntime
    from chattwin.storage import bindings

    store, _, channel, coordinator, _, _ = runtime
    await coordinator.command(
        "review-binding",
        ModeCommand(command_id="start-dedup", action="enable", expected_control_epoch=0),
    )
    await coordinator.settle()
    await coordinator.incoming(
        "review-binding", "received:replay", "already recorded", sender_id="synthetic-review-peer"
    )

    async def receive():
        yield {
            "user_id": "synthetic-review-peer",
            "message_id": "replay",
            "time": int(datetime.now(timezone.utc).timestamp()),
            "message": [{"type": "text", "data": {"text": "already recorded"}}],
        }

    channel.receive = receive
    binding = Binding.model_validate(store.rows(bindings)[0]["payload"])
    live = LiveRuntime(coordinator, None, binding)
    await live.receive()
    assert live.buffer == []
    assert coordinator.status(binding.id)["context_seq"] == 1
    await coordinator.close()


async def test_live_runtime_drops_pre_enable_platform_backlog(runtime):
    from datetime import datetime, timezone

    from chattwin.channels.runtime import LiveRuntime
    from chattwin.storage import bindings

    store, _, channel, coordinator, _, _ = runtime
    await coordinator.command(
        "review-binding",
        ModeCommand(command_id="start-backlog", action="enable", expected_control_epoch=0),
    )
    await coordinator.settle()

    async def receive():
        yield {
            "user_id": "synthetic-review-peer",
            "message_id": "old-unread",
            "time": int(datetime.now(timezone.utc).timestamp()) - 600,
            "message": [{"type": "text", "data": {"text": "old private unread"}}],
        }

    channel.receive = receive
    binding = Binding.model_validate(store.rows(bindings)[0]["payload"])
    live = LiveRuntime(coordinator, None, binding)
    await live.receive()
    assert live.buffer == []
    assert coordinator.status(binding.id)["context_seq"] == 0
    await coordinator.close()


async def test_live_runtime_old_generation_error_cannot_pause_new_session(runtime):
    from chattwin.channels.runtime import LiveRuntime
    from chattwin.storage import bindings

    store, _, _, coordinator, _, _ = runtime
    await coordinator.command(
        "review-binding",
        ModeCommand(command_id="start-old", action="enable", expected_control_epoch=0),
    )
    await coordinator.settle()
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedEngine:
        async def reply(self, *args, **kwargs):
            entered.set()
            await release.wait()
            raise DomainError("MODEL_UNAVAILABLE", "old delayed failure", 503)

    binding = Binding.model_validate(store.rows(bindings)[0]["payload"])
    live = LiveRuntime(coordinator, DelayedEngine(), binding)
    generation = asyncio.create_task(live.generate("synthetic", "synthetic-event"))
    await entered.wait()
    stopped = await coordinator.command(
        binding.id, ModeCommand(command_id="stop-old", action="takeover")
    )
    await coordinator.settle()
    await coordinator.command(
        binding.id,
        ModeCommand(
            command_id="start-new", action="enable", expected_control_epoch=stopped["control_epoch"]
        ),
    )
    await coordinator.settle()
    before = coordinator.status(binding.id)
    release.set()
    await generation
    after = coordinator.status(binding.id)
    assert after["mode"] == "AI_ACTIVE"
    assert after["control_epoch"] == before["control_epoch"]
    await coordinator.close()
