from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"


def test_run_and_read_selection():
    with TestClient(app) as client:
        run = client.post("/api/jobs/run-selection", json={"trade_date": "2099-01-02"})
        assert run.status_code == 200
        data = client.get("/api/selections?date=2099-01-02").json()
        assert data["count"] >= 1
        assert "reasons" in data["items"][0]
