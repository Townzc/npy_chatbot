from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from chattwin.api import create_app
from chattwin.domain import DomainError, GenerationRequest
from chattwin.models import HTTPProvider


def test_authenticated_demo_flow(tmp_path):
    app = create_app(tmp_path, token="test-only")
    with TestClient(app) as client:
        assert client.get("/api/v1/state").status_code == 401
        assert client.post("/api/v1/demo").status_code == 401
        client.headers["Authorization"] = "Bearer test-only"
        state = client.post("/api/v1/demo").json()
        assert len(state["personas"]) == 1
        assert client.post("/api/v1/demo").json() == state
        scope = {
            "persona_id": state["personas"][0]["id"],
            "relationship_id": state["relationships"][0]["id"],
        }
        assert (
            client.post(
                "/api/v1/sandbox/messages", json={"binding_id": "demo-binding", "text": "hello"}
            ).status_code
            == 409
        )
        mode_url = "/api/v1/conversations/demo-binding/mode"
        assert (
            client.post(
                mode_url, json={"command_id": "1", "action": "enable", "expected_control_epoch": 99}
            ).status_code
            == 409
        )
        result = client.post(
            mode_url, json={"command_id": "2", "action": "enable", "expected_control_epoch": 0}
        ).json()
        assert result["mode"] == "AI_ACTIVE"
        reply = client.post(
            "/api/v1/sandbox/messages",
            json={"binding_id": "demo-binding", "text": "周末去看展", "variant": "B2"},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["synthetic"] is True
        stopped = client.post(
            mode_url, json={"command_id": "3", "action": "takeover", "expected_control_epoch": -999}
        ).json()
        assert stopped["mode"] == "HUMAN"
        assert [n["text"] for n in stopped["notifications"]] == ["对方已切换为ai模式", "本人已接管"]
        dataset = client.post("/api/v1/datasets", json=scope)
        assert dataset.status_code == 200, dataset.text


def test_origin_host_and_upload_boundaries(tmp_path):
    with TestClient(create_app(tmp_path, token="test")) as client:
        client.headers["Authorization"] = "Bearer test"
        assert (
            client.post("/api/v1/demo", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400
        response = client.post(
            "/api/v1/imports/inspect", files={"file": ("../../evil.csv", b"a,b\n1,2", "text/csv")}
        )
        assert response.status_code in (200, 422)
        assert not (tmp_path.parent / "evil.csv").exists()
        fixture = Path("examples/chatlab_wechat.synthetic.jsonl").read_bytes()
        result = client.post(
            "/api/v1/imports/inspect",
            files={"file": ("synthetic.jsonl", fixture, "application/json")},
        )
        assert result.status_code == 200, result.text
        assert result.json()["senders"]


async def test_http_provider_scope_budget_and_bad_response():
    def respond(request):
        import json

        body = json.loads(request.content)
        assert body["metadata"] == {"persona_id": "p", "relationship_id": "r"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "local protocol response"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )

    provider = HTTPProvider(
        "http://test/v1",
        "test-model",
        "test-key",
        max_calls=1,
        transport=httpx.MockTransport(respond),
    )
    request = GenerationRequest(
        persona_id="p", relationship_id="r", messages=[{"role": "user", "content": "hello"}]
    )
    result = await provider.generate(request)
    assert result.output_tokens == 3
    with pytest.raises(DomainError, match="budget"):
        await provider.generate(request)
    invalid = HTTPProvider(
        "http://test/v1",
        "m",
        "k",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})),
    )
    with pytest.raises(DomainError, match="invalid response"):
        await invalid.generate(request)
