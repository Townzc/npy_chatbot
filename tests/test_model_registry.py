"""Endpoint protocol tests are synthetic; real adapter roundtrip lives in training tests."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chattwin.api import create_app
from chattwin.domain import Binding, ModeCommand
from chattwin.models.registry import ActivateDeployment
from chattwin.storage import outbox


@pytest.fixture
def registry_client(tmp_path):
    app = create_app(tmp_path, token="synthetic-owner")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "synthetic protocol reply"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )

    app.state.registry.transport = httpx.MockTransport(respond)
    with TestClient(app, headers={"Authorization": "Bearer synthetic-owner"}) as client:
        state = client.post("/api/v1/demo").json()
        scope = {
            "persona_id": state["personas"][0]["id"],
            "relationship_id": state["relationships"][0]["id"],
        }
        yield app, client, scope, calls


def create_deployment(client, scope):
    response = client.post(
        "/api/v1/model-deployments",
        json={
            **scope,
            "endpoint": "http://testserver/v1",
            "model": "protocol-test",
            "label": "Synthetic protocol test",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_verified_model_switch_stops_old_generation_and_rolls_back(registry_client):
    app, client, scope, calls = registry_client
    dep = create_deployment(client, scope)
    body = {"binding_id": "demo-binding", "expected_control_epoch": 0}
    assert client.post(f"/api/v1/model-deployments/{dep}/activate", json=body).status_code == 409
    assert client.post(f"/api/v1/model-deployments/{dep}/test").json()["status"] == "ready"
    activated = client.post(f"/api/v1/model-deployments/{dep}/activate", json=body).json()
    status = activated["status"]
    assert status["mode"] == "HUMAN" and status["payload"]["model_deployment_id"] == dep
    assert client.post(f"/api/v1/model-deployments/{dep}/activate", json=body).status_code == 409
    enabled = client.post(
        "/api/v1/conversations/demo-binding/mode",
        json={
            "command_id": "enable",
            "action": "enable",
            "expected_control_epoch": status["control_epoch"],
        },
    ).json()
    response = client.post(
        "/api/v1/sandbox/messages", json={"binding_id": "demo-binding", "text": "hello"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "http:protocol-test"
    client.post(
        "/api/v1/sandbox/messages", json={"binding_id": "demo-binding", "text": "and then?"}
    )
    assert [m["role"] for m in calls[-1]["messages"]] == ["system", "user", "assistant", "user"]
    rolled = client.post(
        "/api/v1/model-deployments/rollback",
        json={**body, "expected_control_epoch": enabled["control_epoch"]},
    ).json()
    assert rolled["status"]["mode"] == "PAUSED"
    assert rolled["status"]["payload"]["model_deployment_id"] == "mock-v1"
    assert (
        client.post(
            "/api/v1/sandbox/messages", json={"binding_id": "demo-binding", "text": "stopped"}
        ).status_code
        == 409
    )


def test_endpoint_validation_auth_and_relationship_isolation(registry_client):
    app, client, scope, _ = registry_client
    dep = create_deployment(client, scope)
    client.post(f"/api/v1/model-deployments/{dep}/test")
    other = client.post(
        "/api/v1/relationships",
        json={"persona_id": scope["persona_id"], "name": "Another synthetic friend"},
    ).json()
    binding = client.post("/api/v1/bindings", json={**scope, "relationship_id": other["id"]}).json()
    result = client.post(
        f"/api/v1/model-deployments/{dep}/activate",
        json={"binding_id": binding["id"], "expected_control_epoch": 0},
    )
    assert result.status_code == 403 and result.json()["code"] == "MODEL_SCOPE_MISMATCH"
    for url in (
        "http://remote.example/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?key=secret",
    ):
        assert (
            client.post(
                "/api/v1/model-deployments",
                json={**scope, "endpoint": url, "model": "m", "label": "invalid"},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/v1/model-deployments",
            json={
                **scope,
                "endpoint": "https://example.com/v1",
                "model": "m",
                "label": "invalid",
                "key_env": "CHATTWIN_ONEBOT_TOKEN",
            },
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/model-deployments", params=scope, headers={"Authorization": "invalid"}
        ).status_code
        == 401
    )


def test_artifact_rejection_and_b3_requires_genuine_registered_artifact(registry_client, tmp_path):
    app, client, scope, _ = registry_client
    assert (
        client.post(
            "/api/v1/model-artifacts", json={**scope, "artifact_path": str(tmp_path / "missing")}
        ).status_code
        == 422
    )
    client.post(
        "/api/v1/conversations/demo-binding/mode",
        json={"command_id": "e", "action": "enable", "expected_control_epoch": 0},
    )
    response = client.post(
        "/api/v1/sandbox/messages",
        json={"binding_id": "demo-binding", "text": "hello", "variant": "B3"},
    )
    assert response.status_code == 422 and response.json()["code"] == "ADAPTER_REQUIRED"


async def test_model_switch_cannot_skip_unresolved_notice(tmp_path):
    from chattwin.channels import FakeChannel
    from chattwin.domain import DomainError
    from chattwin.importers import DataService
    from chattwin.models import MockProvider
    from chattwin.models.registry import ModelRegistry
    from chattwin.outbox import Coordinator
    from chattwin.storage import Store

    store = Store(tmp_path)
    store.migrate()
    data = DataService(store)
    persona = data.create_persona("Synthetic")
    relation = data.create_relationship(persona["id"], "Synthetic friend")
    coordinator = Coordinator(store, FakeChannel())
    binding = Binding(
        persona_id=persona["id"],
        relationship_id=relation["id"],
        channel_account_id="synthetic-account",
        conversation_id="synthetic",
        recipient_id="synthetic",
    )
    coordinator.create_binding(binding)
    await coordinator.command(
        binding.id, ModeCommand(command_id="enable", action="enable", expected_control_epoch=0)
    )
    registry = ModelRegistry(store, MockProvider(), lambda: coordinator)
    with pytest.raises(DomainError, match="notification"):
        await registry.activate(
            "mock-v1", ActivateDeployment(binding_id=binding.id, expected_control_epoch=1)
        )
    assert len(store.rows(outbox)) == 1
    await coordinator.close()
    store.close()


def test_restored_artifact_catalog_remains_readable_and_unavailable(
    registry_client, tmp_path_factory
):
    from chattwin.domain import now, uid
    from chattwin.models.registry import ArtifactRecord
    from chattwin.ops import create_backup, restore_backup
    from chattwin.storage import artifacts

    app, _, scope, _ = registry_client
    # Metadata-only fixture exercises restore schema; it is never accepted as a
    # trained artifact and does not provide training evidence.
    artifact = ArtifactRecord(
        **scope,
        id=uid(),
        artifact_path="/nonexistent/synthetic-model",
        status="unavailable",
        manifest={},
        manifest_hash="0" * 64,
        created_at=now().isoformat(),
    )
    with app.state.store.transaction() as conn:
        conn.execute(
            artifacts.insert().values(id=artifact.id, **scope, payload=artifact.model_dump())
        )
    work = tmp_path_factory.mktemp("restore-catalog")
    create_backup(app.state.store, work / "backup")
    restore_backup(work / "backup", work / "restored")
    with TestClient(
        create_app(work / "restored", token="synthetic-restored"),
        headers={"Authorization": "Bearer synthetic-restored"},
    ) as client:
        response = client.get("/api/v1/model-artifacts", params=scope)
        assert response.status_code == 200, response.text
        item = response.json()[0]
        assert item["status"] == "unavailable" and item["restore_requires_verification"]
        assert item["restore_reason"] and item["deployment_status"] == "unavailable"
        denied = client.post(
            "/api/v1/model-deployments",
            json={
                **scope,
                "artifact_id": artifact.id,
                "endpoint": "http://testserver/v1",
                "model": "chattwin-adapter",
                "label": "restored",
            },
        )
        assert denied.status_code == 409
