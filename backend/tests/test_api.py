from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import db
from app.db import compat as db_compat
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


def test_selection_import_preserves_local_display_fields_and_js_aliases(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    payload = _import_payload(
        trade_date="2030-02-01",
        items=[{
            "code": "300701", "name": "工大高科", "score": 92,
            "price": 18.65, "changePercent": 4.21, "industry": "软件开发",
            "turnoverRate": 12.8, "continuousBoard": 2,
            "strategy_name": "超短线技术共振", "reasons": ["量价共振"],
        }],
    )
    with TestClient(app) as client:
        response = client.post("/api/selections/import", json=payload, headers=headers)
        selections = client.get("/api/selections?date=2030-02-01&strategy=超短线技术共振")
    assert response.status_code == 200
    assert selections.status_code == 200
    item = selections.json()["data"]["items"][0]
    assert item == {
        "code": "300701", "name": "工大高科", "trade_date": "2030-02-01",
        "price": 18.65, "change_pct": 4.21, "score": 92.0,
        "strategy_name": "超短线技术共振", "industry": "软件开发",
        "turnover_rate": 12.8, "board_count": 2,
        "reasons": ["量价共振"], "indicators": {},
    }


def test_selection_performance_uses_real_kline_positions_and_reports_missing_future_data(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    code, strategy, selection_date = "300702", "超短线技术共振", date(2030, 3, 1)
    with TestClient(app) as client:
        imported = client.post("/api/selections/import", json=_import_payload(
            trade_date=selection_date.isoformat(),
            items=[_selection_item(code, 88, strategy)],
        ), headers=headers)
        assert imported.status_code == 200
        db.save_daily_quotes([
            {
                "code": code, "name": f"测试{code}",
                "trade_date": (selection_date + timedelta(days=index)).isoformat(),
                "open": close, "high": close, "low": close, "close": close, "volume": 1000,
            }
            for index, close in enumerate((10, 11, 9, 12))
        ])
        response = client.get(
            f"/api/selections/{code}/performance?date={selection_date.isoformat()}&strategy={strategy}"
        )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["base_close"] == 10.0
    periods = {item["label"]: item for item in payload["periods"]}
    assert periods["1d"] == {
        "label": "1d", "trading_days": 1, "target_date": "2030-03-02",
        "close": 11.0, "return_pct": 10.0, "status": "ok",
    }
    assert periods["3d"]["return_pct"] == 20.0
    assert periods["5d"] == {
        "label": "5d", "trading_days": 5, "target_date": None,
        "close": None, "return_pct": None, "status": "暂无数据",
    }
    assert periods["3m"]["trading_days"] == 60
    assert periods["3m"]["status"] == "暂无数据"


def _selection_item(code: str, score: float, strategy_name: str = "默认策略") -> dict:
    return {"code": code, "name": f"测试{code}", "score": score, "strategy_name": strategy_name}


def test_selection_import_defaults_to_upsert_without_deleting_other_items(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    date_value = "2030-01-02"
    with TestClient(app) as client:
        seed = _import_payload(trade_date=date_value, items=[
            _selection_item("300801", 70), _selection_item("300802", 71),
        ])
        assert client.post("/api/selections/import", json=seed, headers=headers).status_code == 200
        update = _import_payload(trade_date=date_value, items=[_selection_item("300801", 90)])
        assert client.post("/api/selections/import", json=update, headers=headers).status_code == 200
        rows = client.get(f"/api/selections?date={date_value}").json()["data"]["items"]
    assert {row["code"] for row in rows} == {"300801", "300802"}
    assert next(row for row in rows if row["code"] == "300801")["score"] == 90


def test_selection_import_replace_existing_replaces_only_target_strategy_and_date(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    target_date, other_date = "2030-01-03", "2030-01-04"
    with TestClient(app) as client:
        assert client.post("/api/selections/import", json=_import_payload(trade_date=target_date, items=[
            _selection_item("300811", 70), _selection_item("300812", 71),
            _selection_item("300813", 72, "其他策略"),
        ]), headers=headers).status_code == 200
        assert client.post("/api/selections/import", json=_import_payload(trade_date=other_date, items=[
            _selection_item("300814", 73),
        ]), headers=headers).status_code == 200
        replacement = _import_payload(trade_date=target_date, replace_existing=True, items=[
            _selection_item("300815", 95),
        ])
        assert client.post("/api/selections/import", json=replacement, headers=headers).status_code == 200
        target_rows = client.get(f"/api/selections?date={target_date}").json()["data"]["items"]
        other_rows = client.get(f"/api/selections?date={other_date}").json()["data"]["items"]
    assert {row["code"] for row in target_rows} == {"300813", "300815"}
    assert {row["code"] for row in other_rows} == {"300814"}


def test_selection_import_replace_rejects_empty_unauthorised_and_multi_strategy_without_deleting(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    date_value = "2030-01-05"
    with TestClient(app) as client:
        assert client.post("/api/selections/import", json=_import_payload(trade_date=date_value, items=[
            _selection_item("300821", 80),
        ]), headers=headers).status_code == 200
        assert client.post("/api/selections/import", json={
            "trade_date": date_value, "replace_existing": True, "items": [],
        }, headers=headers).status_code == 422
        assert client.post("/api/selections/import", json=_import_payload(
            trade_date=date_value, replace_existing=True,
            items=[_selection_item("300822", 80), _selection_item("300823", 80, "其他策略")],
        ), headers=headers).status_code == 422
        assert client.post("/api/selections/import", json=_import_payload(
            trade_date=date_value, replace_existing=True, items=[_selection_item("300824", 80)],
        )).status_code == 401
        rows = client.get(f"/api/selections?date={date_value}").json()["data"]["items"]
    assert [row["code"] for row in rows] == ["300821"]


def test_selection_import_replace_rolls_back_delete_when_write_fails(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    date_value = "2030-01-06"
    with TestClient(app) as client:
        assert client.post("/api/selections/import", json=_import_payload(trade_date=date_value, items=[
            _selection_item("300831", 80),
        ]), headers=headers).status_code == 200

    original_upsert = db_compat.selection_results.upsert

    def fail_second_write(session, *, values, commit=True):
        if values["stock_code"] == "300833":
            raise RuntimeError("forced write failure")
        return original_upsert(session, values=values, commit=commit)

    monkeypatch.setattr(db_compat.selection_results, "upsert", fail_second_write)
    failed = _import_payload(trade_date=date_value, replace_existing=True, items=[
        _selection_item("300832", 90), _selection_item("300833", 91),
    ])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/selections/import", json=failed, headers=headers)
        rows = client.get(f"/api/selections?date={date_value}").json()["data"]["items"]
    assert response.status_code == 500
    assert [row["code"] for row in rows] == ["300831"]


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
