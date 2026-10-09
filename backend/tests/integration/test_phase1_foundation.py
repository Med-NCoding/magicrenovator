from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app
from app.settings import get_settings
from tests.conftest import create_authenticated_client


def test_health_and_readiness_and_default_mock_mode() -> None:
    settings = get_settings()
    assert settings.GATEWAY_MODE == "mock"

    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert "X-Correlation-ID" in h.headers

    r = client.get("/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ready"
    assert data["gateway_mode"] == "mock"


def test_session_and_owner_isolation_on_project_crud() -> None:
    client_a, _ = create_authenticated_client()
    client_b, _ = create_authenticated_client()

    # Session A creates a project
    create_res = client_a.post("/api/projects", json={"name": "Session A Kitchen Remodel"})
    assert create_res.status_code == 201
    proj_a = create_res.json()
    project_id = proj_a["id"]
    assert proj_a["name"] == "Session A Kitchen Remodel"

    # Session A lists projects and sees it
    list_a = client_a.get("/api/projects")
    assert list_a.status_code == 200
    assert any(p["id"] == project_id for p in list_a.json()["items"])

    # Session B lists projects and does NOT see Session A's project
    list_b = client_b.get("/api/projects")
    assert list_b.status_code == 200
    assert not any(p["id"] == project_id for p in list_b.json()["items"])

    # Session B attempting to read or delete Session A's project gets 404 (not 403, avoiding existence leak)
    get_b = client_b.get(f"/api/projects/{project_id}")
    assert get_b.status_code == 404
    assert get_b.json()["error"]["code"] == "not_found"

    del_b = client_b.delete(f"/api/projects/{project_id}")
    assert del_b.status_code == 404

    # Session A deletes its own project -> tombstoned and no longer returned
    del_a = client_a.delete(f"/api/projects/{project_id}")
    assert del_a.status_code == 200
    assert del_a.json()["status"] == "tombstoned"

    get_a_after = client_a.get(f"/api/projects/{project_id}")
    assert get_a_after.status_code == 404
