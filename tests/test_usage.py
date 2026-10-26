"""Monthly reservation failures, restart persistence and concurrent requests."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from chattwin.api import create_app
from chattwin.domain import DomainError, GenerationRequest, GenerationResult
from chattwin.importers import DataService
from chattwin.storage import Store
from chattwin.usage import BudgetService, UsagePolicy


@pytest.fixture
def budget(tmp_path):
    store = Store(tmp_path)
    store.migrate()
    data = DataService(store)
    persona = data.create_persona("Synthetic budget")
    relation = data.create_relationship(persona["id"], "Synthetic friend")
    service = BudgetService(store)
    request = GenerationRequest(
        persona_id=persona["id"],
        relationship_id=relation["id"],
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8,
    )
    yield service, request
    store.close()


def test_atomic_reservation_survives_restart_and_unknown_usage(budget):
    service, request = budget
    service.update(UsagePolicy(persona_id=request.persona_id, monthly_requests=1))

    def submit(_):
        try:
            return service.reserve(request, "http:synthetic", "test", "B2")
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(submit, range(4)))
    assert ids.count("MONTHLY_BUDGET_EXHAUSTED") == 3
    reservation = next(i for i in ids if i != "MONTHLY_BUDGET_EXHAUSTED")
    before = service.summary(request.persona_id)
    service.finish(reservation, None)
    restarted = BudgetService(service.store)
    after = restarted.summary(request.persona_id)
    assert after.input_tokens == before.input_tokens and after.output_tokens == 8
    assert after.requests == 1 and after.unresolved_requests == 1 and after.exhausted
    with pytest.raises(DomainError):
        restarted.reserve(request, "http:synthetic", "test", "B2")


def test_actual_usage_settles_once_and_policy_has_optimistic_version(budget):
    service, request = budget
    original = UsagePolicy(
        persona_id=request.persona_id,
        monthly_requests=3,
        input_usd_per_million=1,
        output_usd_per_million=2,
        monthly_usd=1,
    )
    service.update(original)
    with pytest.raises(DomainError, match="Refresh"):
        service.update(original)
    reservation = service.reserve(request, "http:synthetic", "test", "B2")
    service.finish(
        reservation,
        GenerationResult(
            text="yes", model="http:synthetic", input_tokens=5, output_tokens=2, usage_reported=True
        ),
    )
    service.finish(reservation, None)
    summary = service.summary(request.persona_id)
    assert summary.input_tokens == 5 and summary.output_tokens == 2
    assert summary.estimated_usd == pytest.approx(0.000009)
    assert summary.unresolved_requests == 0
    missing = service.reserve(request, "http:synthetic", "test", "B2")
    service.finish(missing, GenerationResult(text="no usage", model="http:synthetic"))
    assert service.summary(request.persona_id).unresolved_requests == 1


def test_budget_api_and_exhaustion_pauses_ai_before_network(tmp_path):
    import httpx

    app = create_app(tmp_path, token="synthetic-owner")
    calls = []
    app.state.registry.transport = httpx.MockTransport(
        lambda request: (
            calls.append(request)
            or httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "synthetic"}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                },
            )
        )
    )
    with TestClient(app, headers={"Authorization": "Bearer synthetic-owner"}) as client:
        state = client.post("/api/v1/demo").json()
        persona = state["personas"][0]["id"]
        scope = {"persona_id": persona, "relationship_id": state["relationships"][0]["id"]}
        dep = client.post(
            "/api/v1/model-deployments",
            json={**scope, "endpoint": "http://testserver/v1", "model": "test", "label": "test"},
        ).json()["id"]
        assert client.post(f"/api/v1/model-deployments/{dep}/test").status_code == 200
        status = client.post(
            f"/api/v1/model-deployments/{dep}/activate",
            json={"binding_id": "demo-binding", "expected_control_epoch": 0},
        ).json()["status"]
        assert (
            client.put(
                "/api/v1/usage/policy", json={"persona_id": persona, "monthly_requests": 1}
            ).status_code
            == 200
        )
        client.post(
            "/api/v1/conversations/demo-binding/mode",
            json={
                "command_id": "e",
                "action": "enable",
                "expected_control_epoch": status["control_epoch"],
            },
        )
        response = client.post(
            "/api/v1/sandbox/messages",
            json={"binding_id": "demo-binding", "text": "blocked before network"},
        )
        assert response.status_code == 429
        assert len(calls) == 1
        assert client.get("/api/v1/conversations/demo-binding/status").json()["mode"] == "PAUSED"
        summary = client.get("/api/v1/usage", params={"persona_id": persona}).json()
        assert summary["requests"] == 1 and summary["exhausted"]
        assert (
            client.get(
                "/api/v1/usage",
                params={"persona_id": persona},
                headers={"Authorization": "invalid"},
            ).status_code
            == 401
        )
