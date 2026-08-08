from fastapi.testclient import TestClient

from app import db
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


def test_stock_kline_returns_empty_when_only_stock_master_exists():
    db.save_selections([{
        "code": "301234", "name": "无行情股票", "trade_date": "2026-08-07", "score": 80,
    }])
    with TestClient(app) as client:
        response = client.get("/api/stock/301234/kline?period=daily")
    assert response.status_code == 200
    assert response.json() == {"code": 0, "data": [], "message": ""}


def test_stock_kline_uses_persisted_daily_quotes_in_echarts_order():
    db.save_daily_quotes([
        {
            "code": "002001", "name": "真实日线", "trade_date": "2026-08-06",
            "open": 10.1, "high": 11.5, "low": 9.8, "close": 11.2, "volume": 123456,
        },
        {
            "code": "002001", "name": "真实日线", "trade_date": "2026-08-07",
            "open": 11.3, "high": 12.0, "low": 10.9, "close": 11.8, "volume": 234567,
        },
    ])
    with TestClient(app) as client:
        daily = client.get("/api/stock/002001/kline?period=daily")
        weekly = client.get("/api/stock/002001/kline?period=weekly")
    assert daily.status_code == 200
    assert daily.json()["data"] == [
        ["2026-08-06", 10.1, 11.2, 9.8, 11.5, 123456.0],
        ["2026-08-07", 11.3, 11.8, 10.9, 12.0, 234567.0],
    ]
    assert weekly.status_code == 200
    assert weekly.json()["data"] == [["2026-08-07", 10.1, 11.8, 9.8, 12.0, 358023.0]]


def _quote_import_payload(**overrides):
    payload = {
        "quotes": [{
            "stock_code": "301080", "stock_name": "易明医药", "trade_date": "2026-08-07",
            "open": 10.1, "high": 11.5, "low": 9.8, "close": 11.2, "volume": 123456,
        }],
    }
    payload.update(overrides)
    return payload


def test_quote_import_requires_configured_token(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    with TestClient(app) as client:
        response = client.post("/api/quotes/import", json=_quote_import_payload())
    assert response.status_code == 401


def test_quote_import_validates_input(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    invalid_quotes = [
        {"stock_code": "30108", "stock_name": "测试", "trade_date": "2026-08-07", "open": 1, "high": 2, "low": 1, "close": 1, "volume": 1},
        {"stock_code": "301080", "stock_name": "测试", "trade_date": "20260807", "open": 1, "high": 2, "low": 1, "close": 1, "volume": 1},
        {"stock_code": "301080", "stock_name": "测试", "trade_date": "2026-08-07", "open": 1, "high": 1, "low": 2, "close": 1, "volume": 1},
        {"stock_code": "301080", "stock_name": "测试", "trade_date": "2026-08-07", "open": 1, "high": 2, "low": 1, "close": "NaN", "volume": 1},
    ]
    with TestClient(app) as client:
        assert client.post("/api/quotes/import", json={"quotes": []}, headers=headers).status_code == 422
        for quote in invalid_quotes:
            response = client.post("/api/quotes/import", json={"quotes": [quote]}, headers=headers)
            assert response.status_code == 422


def test_quote_import_persists_echarts_kline_and_overwrites_duplicate(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        first = client.post("/api/quotes/import", json=_quote_import_payload(), headers=headers)
        assert first.status_code == 200
        assert first.json()["data"] == {
            "count": 1, "start_date": "2026-08-07", "end_date": "2026-08-07",
        }

        replacement = _quote_import_payload(quotes=[{
            "stock_code": "301080", "stock_name": "易明医药", "trade_date": "2026-08-07",
            "open": 11.0, "high": 12.0, "low": 10.5, "close": 11.8, "volume": 234567,
        }])
        assert client.post("/api/quotes/import", json=replacement, headers=headers).status_code == 200
        kline = client.get("/api/stock/301080/kline?period=daily")
    assert kline.status_code == 200
    assert kline.json()["data"] == [["2026-08-07", 11.0, 11.8, 10.5, 12.0, 234567.0]]
