import pytest
from fastapi.testclient import TestClient

from chattwin.api import create_app
from chattwin.auth import OwnerAuth
from chattwin.domain import DomainError


def test_session_expiry_revocation_and_restart():
    current = [100.0]
    auth = OwnerAuth("synthetic-owner", require_session=True, clock=lambda: current[0])
    session = auth.issue("synthetic-owner", "test", 60)
    assert auth.valid(session.token) and not auth.valid("synthetic-owner")
    assert session.token not in auth.sessions  # only hashes retained
    current[0] = 160
    assert not auth.valid(session.token)
    second = auth.issue("synthetic-owner", "test", 60)
    auth.revoke(second.token)
    assert not auth.valid(second.token)
    third = auth.issue("synthetic-owner", "test", 60)
    assert not OwnerAuth("synthetic-owner", require_session=True).valid(third.token)


def test_failed_login_throttle_does_not_block_existing_stop_credentials():
    current = [100.0]
    auth = OwnerAuth("synthetic-owner", require_session=True, clock=lambda: current[0])
    active = auth.issue("synthetic-owner", "test", 60)
    for _ in range(5):
        with pytest.raises(DomainError) as error:
            auth.issue("wrong", "test", 60)
        assert error.value.status == 401
    with pytest.raises(DomainError) as error:
        auth.issue("wrong", "test", 60)
    assert error.value.status == 429
    assert auth.valid(active.token)
    current[0] += 61
    assert auth.issue("synthetic-owner", "test", 60)


def test_browser_session_origin_and_strict_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATTWIN_REQUIRE_SESSION", "1")
    with TestClient(create_app(tmp_path, token="synthetic-owner")) as client:
        owner = {"Authorization": "Bearer synthetic-owner"}
        assert client.get("/api/v1/state", headers=owner).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/session", headers={**owner, "Origin": "https://evil.example"}, json={}
            ).status_code
            == 403
        )
        issued = client.post("/api/v1/auth/session", headers=owner, json={})
        assert issued.status_code == 200
        session = {"Authorization": "Bearer " + issued.json()["token"]}
        assert client.post("/api/v1/demo", headers=session).status_code == 200
        assert client.post("/api/v1/auth/session", headers=session, json={}).status_code == 401
        client.delete("/api/v1/auth/session", headers=session)
        assert client.get("/api/v1/state", headers=session).status_code == 401
