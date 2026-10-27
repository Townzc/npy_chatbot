import json

import pytest
from websockets.asyncio.server import serve

from chattwin.channels.onebot import OneBotAdapter
from chattwin.domain import Binding, DomainError, SendRequest


@pytest.fixture
async def bridge():
    calls = []

    async def handler(ws):
        async for raw in ws:
            body = json.loads(raw)
            calls.append(body)
            if body["action"] == "get_login_info":
                data = {"user_id": 123}
            elif body["action"] == "get_version_info":
                data = {"app_name": "synthetic-onebot", "app_version": "test"}
            elif body["action"] == "get_status":
                data = {"online": True, "good": True}
            else:
                assert body["params"]["message"] == [
                    {"type": "text", "data": {"text": "[CQ:at,qq=all] just text"}}
                ]
                data = {"message_id": 456}
            await ws.send(
                json.dumps({"echo": body["echo"], "status": "ok", "retcode": 0, "data": data})
            )

    async with serve(handler, "127.0.0.1", 0) as server:
        yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", calls


async def test_read_only_probe_and_identity_mismatch(bridge):
    url, calls = bridge
    adapter = OneBotAdapter(url, "123")
    try:
        report = await adapter.open()
        assert report["identity_verified"]
        assert report["online"] and report["healthy"]
        assert not report["real_conversation_verified"]
        assert [c["action"] for c in calls] == [
            "get_login_info",
            "get_version_info",
            "get_status",
        ]
    finally:
        await adapter.close()
    wrong = OneBotAdapter(url, "999")
    with pytest.raises(DomainError, match="identity"):
        await wrong.open()
    assert calls[-1]["action"] == "get_login_info"
    assert not wrong.verified


@pytest.mark.parametrize(
    "status",
    [
        {"online": False, "good": True},
        {"online": True, "good": False},
        {"good": True},
        {"online": "true", "good": True},
        [],
        None,
    ],
)
async def test_probe_rejects_offline_or_unproven_health(status):
    async def handler(ws):
        async for raw in ws:
            body = json.loads(raw)
            if body["action"] == "get_login_info":
                data = {"user_id": 123}
            elif body["action"] == "get_version_info":
                data = {"app_name": "synthetic-onebot", "app_version": "test"}
            else:
                assert body["action"] == "get_status"
                data = status
            await ws.send(
                json.dumps({"echo": body["echo"], "status": "ok", "retcode": 0, "data": data})
            )

    async with serve(handler, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        adapter = OneBotAdapter(url, "123")
        with pytest.raises(DomainError, match="offline or not healthy"):
            await adapter.open()
        assert not adapter.verified
        assert adapter.reader is not None and adapter.reader.done()


async def test_literal_text_and_explicit_sending_gate(bridge):
    url, calls = bridge
    adapter = OneBotAdapter(url, "123")
    await adapter.open()
    request = SendRequest(
        outbox_id="out",
        binding=Binding(
            persona_id="p",
            relationship_id="r",
            channel_account_id="123",
            conversation_id="789",
            recipient_id="789",
            channel="onebot",
        ),
        kind="ai_reply",
        text="[CQ:at,qq=all] just text",
    )
    denied = await (await adapter.send_text(request))
    assert denied.status == "rejected"
    adapter.allow_send = True
    adapter.allowed_recipients.add("789")
    receipt = await (await adapter.send_text(request))
    assert receipt.platform_message_id == "456"
    assert not adapter.capabilities().idempotent_send
    assert (await adapter.reconcile("out")).status == "unknown"
    await adapter.close()


@pytest.mark.parametrize(
    "url", ["ws://public.example/", "https://localhost/", "ws://localhost/?token=secret"]
)
def test_no_insecure_remote_or_url_credentials(url):
    with pytest.raises(ValueError):
        OneBotAdapter(url, "123")
