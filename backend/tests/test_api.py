from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"


def test_list_stocks_has_api_envelope():
    with TestClient(app) as client:
        response = client.get("/api/stocks?page=1&size=10")
        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        assert {"items", "page", "size", "total"} <= payload["data"].keys()


def test_run_selection_requires_configured_token(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    with TestClient(app) as client:
        response = client.post("/api/selections/run", json={"trade_date": "2099-01-02"})
        assert response.status_code == 401


def test_quote_sync_requires_configured_token(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    with TestClient(app) as client:
        response = client.post("/api/quotes/sync", json={"date": "2026-08-07"})
        assert response.status_code == 401
