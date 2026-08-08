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


def _import_payload(**overrides):
    payload = {
        "trade_date": "2026-08-07",
        "items": [{
            "code": "600519", "name": "贵州茅台", "score": 91.5,
            "price": 1500.0, "change_pct": 1.2, "strategy_name": "默认策略",
            "industry": "白酒", "reasons": ["趋势向上"], "indicators": {"rsi": 55},
        }],
    }
    payload.update(overrides)
    return payload


def test_selection_import_requires_configured_token(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    with TestClient(app) as client:
        response = client.post("/api/selections/import", json=_import_payload())
    assert response.status_code == 401


def test_selection_import_validates_payload(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        for payload in (
            _import_payload(trade_date="20260807"),
            _import_payload(items=[]),
            _import_payload(items=[{"code": "600519", "name": "贵州茅台", "score": 101}]),
            _import_payload(items=[{"code": "600519", "name": "贵州茅台", "score": "NaN"}]),
        ):
            response = client.post("/api/selections/import", json=payload, headers=headers)
            assert response.status_code == 422


def test_selection_import_persists_and_overwrites_same_strategy(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        first = client.post("/api/selections/import", json=_import_payload(), headers=headers)
        assert first.status_code == 200
        assert first.json()["data"] == {"date": "2026-08-07", "count": 1}

        updated = _import_payload(items=[{
            "code": "600519", "name": "贵州茅台", "score": 88.0,
            "reasons": ["本地更新"], "indicators": {"rsi": 60},
        }])
        second = client.post("/api/selections/import", json=updated, headers=headers)
        assert second.status_code == 200

        selections = client.get("/api/selections?date=2026-08-07")
    assert selections.status_code == 200
    assert selections.json()["data"]["count"] == 1
    item = selections.json()["data"]["items"][0]
    assert item["score"] == 88.0
    assert item["reasons"] == ["本地更新"]
