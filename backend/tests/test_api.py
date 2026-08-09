from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app import db
from app.db import compat as db_compat
from app.main import app
from app.models import DailyQuote, IntradayQuote


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"


def _market_snapshot_payload(
    *, as_of: str = "2026-08-08T14:00:00+08:00", source: str = "akshare-sina",
    index_price: float = 3000.0, stock_price: float = 20.0, stock_code: str = "300970",
):
    definitions = [
        ("上证指数", "000001.SH"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SH"),
    ]
    return {
        "indices": [
            {"name": name, "code": code, "available": True, "price": index_price + index,
             "change_pct": 0.1 + index, "observed_at": as_of, "source": source}
            for index, (name, code) in enumerate(definitions)
        ],
        "stocks": [{
            "code": stock_code, "name": "当前价测试", "price": stock_price,
            "change_pct": 2.5, "observed_at": as_of, "source": source,
        }],
    }


def test_market_indices_always_returns_fixed_four_in_order():
    with TestClient(app) as client:
        response = client.get("/api/market/indices")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [(item["name"], item["code"]) for item in items] == [
        ("上证指数", "000001.SH"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SH"),
    ]
    assert all(item["price"] is None and item["as_of"] is None for item in items)


def test_market_snapshot_import_requires_token_and_strict_akshare_contract(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        assert client.post("/api/market/snapshots/import", json=_market_snapshot_payload()).status_code == 401
        invalid_source = _market_snapshot_payload(source="AKShare/Sina")
        assert client.post("/api/market/snapshots/import", json=invalid_source, headers=headers).status_code == 422
        invalid_indices = _market_snapshot_payload()
        invalid_indices["indices"][-1] = dict(invalid_indices["indices"][0])
        assert client.post("/api/market/snapshots/import", json=invalid_indices, headers=headers).status_code == 422
        invalid_price = _market_snapshot_payload(index_price=0)
        assert client.post("/api/market/snapshots/import", json=invalid_price, headers=headers).status_code == 422
        missing_available_value = _market_snapshot_payload()
        missing_available_value["indices"][0]["price"] = None
        assert client.post(
            "/api/market/snapshots/import", json=missing_available_value, headers=headers
        ).status_code == 422


def test_unavailable_index_package_succeeds_without_overwriting_latest(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        initial = _market_snapshot_payload(
            as_of="2026-08-08T12:10:00+08:00", stock_code="300971"
        )
        assert client.post("/api/market/snapshots/import", json=initial, headers=headers).status_code == 200
        unavailable = _market_snapshot_payload(
            as_of="2026-08-08T12:20:00+08:00", index_price=5000, stock_code="300971"
        )
        unavailable_index = unavailable["indices"][3]
        unavailable_index.update(available=False, price=None, change_pct=None, observed_at=None)
        response = client.post("/api/market/snapshots/import", json=unavailable, headers=headers)
        items = client.get("/api/market/indices").json()["data"]["items"]
    assert response.status_code == 200
    assert response.json()["data"]["indices"] == 3
    stored_index = next(item for item in items if item["code"] == "000688.SH")
    assert stored_index["price"] == 3003.0
    assert stored_index["as_of"] == "2026-08-08T12:10:00+08:00"


def test_selection_fixed_price_and_current_snapshot_are_not_mixed_and_stale_is_ignored(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    report_date, price_date = "2032-01-04", "2032-01-02"
    selection = _import_payload(trade_date=report_date, items=[{
        "code": "300970", "name": "当前价测试", "score": 90,
        "selection_price": 12.5, "price_date": price_date,
        "change_pct": 1.25, "strategy_name": "超短线技术共振",
    }])
    with TestClient(app) as client:
        assert client.post("/api/selections/import", json=selection, headers=headers).status_code == 200
        newest = client.post(
            "/api/market/snapshots/import", json=_market_snapshot_payload(), headers=headers
        )
        assert newest.status_code == 200
        first = client.get(f"/api/selections?date={report_date}").json()["data"]["items"][0]
        stale = _market_snapshot_payload(
            as_of="2026-08-08T13:00:00+08:00", index_price=1000, stock_price=5,
        )
        assert client.post("/api/market/snapshots/import", json=stale, headers=headers).status_code == 200
        second = client.get(f"/api/selections?date={report_date}").json()["data"]["items"][0]
        indices = client.get("/api/market/indices").json()["data"]["items"]
    assert first["price"] == first["selection_price"] == 12.5
    assert first["selection_price_date"] == price_date
    assert first["current_price"] == 20.0
    assert first["current_price_as_of"] == "2026-08-08T14:00:00+08:00"
    assert first["change_pct"] == 1.25
    assert second["selection_price"] == 12.5 and second["current_price"] == 20.0
    assert indices[0]["price"] == 3000.0
    assert indices[0]["as_of"] == "2026-08-08T14:00:00+08:00"


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
        "price": 18.65, "selection_price": 18.65, "selection_price_date": "2030-02-01",
        "current_price": None, "current_price_as_of": None, "change_pct": 4.21, "score": 92.0,
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
            "amount": 1358024, "source": "akshare-eastmoney",
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
        {"stock_code": "301080", "stock_name": "截图异常", "trade_date": "2026-08-07", "open": 10, "high": 10.2, "low": 9.8, "close": 10.5, "volume": 1},
        {"stock_code": "301080", "stock_name": "来源异常", "trade_date": "2026-08-07", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1, "source": "tencent"},
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
            "amount": 2767890, "source": "akshare-eastmoney",
        }])
        assert client.post("/api/quotes/import", json=replacement, headers=headers).status_code == 200
        kline = client.get("/api/stock/301080/kline?period=daily")
        with db.SessionLocal() as session:
            persisted = session.query(DailyQuote).filter_by(
                stock_code="301080", trade_date=date(2026, 8, 7)
            ).one()
            persisted_contract = (float(persisted.amount), persisted.source)
    assert kline.status_code == 200
    assert kline.json()["data"] == [["2026-08-07", 11.0, 11.8, 10.5, 12.0, 234567.0]]
    assert persisted_contract == (2767890.0, "akshare-eastmoney")


def _intraday_import_payload(**overrides):
    payload = {
        "quotes": [{
            "code": "301090", "name": "华润材料", "interval": "30m",
            "datetime": "2026-08-07T09:30:00+08:00",
            "open": 10.1, "high": 10.8, "low": 10.0, "close": 10.5,
            "volume": 123456, "amount": None, "estimated": True,
            "source": "akshare-sina",
        }],
    }
    payload.update(overrides)
    return payload


def test_intraday_quote_import_requires_configured_token(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    with TestClient(app) as client:
        response = client.post("/api/quotes/intraday/import", json=_intraday_import_payload())
    assert response.status_code == 401


def test_intraday_quote_import_validates_contract_and_unknown_stock_name(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    invalid_bars = [
        {**_intraday_import_payload()["quotes"][0], "interval": "15m"},
        {**_intraday_import_payload()["quotes"][0], "code": "30109"},
        {**_intraday_import_payload()["quotes"][0], "high": 9, "low": 10},
        {**_intraday_import_payload()["quotes"][0], "high": 10.2, "close": 10.5},
        {**_intraday_import_payload()["quotes"][0], "source": "sina"},
        {key: value for key, value in _intraday_import_payload()["quotes"][0].items() if key != "estimated"},
    ]
    with TestClient(app) as client:
        assert client.post("/api/quotes/intraday/import", json={"quotes": []}, headers=headers).status_code == 422
        for bar in invalid_bars:
            assert client.post("/api/quotes/intraday/import", json={"quotes": [bar]}, headers=headers).status_code == 422
        nameless = {key: value for key, value in _intraday_import_payload()["quotes"][0].items() if key != "name"}
        assert client.post("/api/quotes/intraday/import", json={"quotes": [nameless]}, headers=headers).status_code == 422


def test_intraday_quote_import_upserts_normalises_timezone_and_keeps_daily_kline(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    headers = {"X-Job-Token": "ci-secret"}
    first = _intraday_import_payload()
    replacement = _intraday_import_payload(quotes=[{
        "stock_code": "301090", "interval": "30m", "datetime": "2026-08-07T01:30:00Z",
        "open": 10.2, "high": 11.0, "low": 10.1, "close": 10.9,
        "volume": 234567, "amount": 2500000, "amount_estimated": False,
        "source": "akshare-sina",
    }])
    with TestClient(app) as client:
        assert client.post("/api/quotes/intraday/import", json=first, headers=headers).status_code == 200
        second = client.post("/api/quotes/intraday/import", json=replacement, headers=headers)
        intraday = client.get("/api/stock/301090/kline?period=30m")
        daily = client.get("/api/stock/301090/kline?period=daily")
        with db.SessionLocal() as session:
            persisted = session.query(IntradayQuote).filter_by(
                stock_code="301090", interval="30m"
            ).one()
            persisted_source = persisted.source
    assert second.status_code == 200
    assert second.json()["data"] == {
        "count": 1,
        "start_datetime": "2026-08-07T09:30:00+08:00",
        "end_datetime": "2026-08-07T09:30:00+08:00",
    }
    assert intraday.json() == {
        "code": 0,
        "data": [["2026-08-07T09:30:00+08:00", 10.2, 10.9, 10.1, 11.0, 234567.0]],
        "message": "",
    }
    assert daily.json() == {"code": 0, "data": [], "message": ""}
    assert persisted_source == "akshare-sina"


def test_intraday_kline_returns_empty_without_persisted_intraday_bars():
    db.save_selections([{
        "code": "301091", "name": "无分钟线股票", "trade_date": "2030-01-01", "score": 80,
    }])
    with TestClient(app) as client:
        response = client.get("/api/stock/301091/kline?period=30m")
    assert response.json() == {"code": 0, "data": [], "message": ""}


def test_kline_outputs_filter_preexisting_rows_that_violate_ohlc_invariants():
    code = "301092"
    with TestClient(app) as client:
        db.save_selections([{
            "code": code, "name": "坏K线过滤", "trade_date": "2030-01-02", "score": 80,
        }])
        with db.SessionLocal.begin() as session:
            session.add(DailyQuote(
                stock_code=code, trade_date=date(2030, 1, 2),
                open=10, high=9, low=8, close=10.5, volume=100,
            ))
            session.add(IntradayQuote(
                stock_code=code, interval="30m", trade_datetime=datetime(2030, 1, 2, 9, 30),
                open=10, high=9, low=8, close=10.5, volume=100,
                amount=None, amount_estimated=False,
            ))
        daily = client.get(f"/api/stock/{code}/kline?period=daily")
        weekly = client.get(f"/api/stock/{code}/kline?period=weekly")
        intraday = client.get(f"/api/stock/{code}/kline?period=30m")
    assert daily.json()["data"] == []
    assert weekly.json()["data"] == []
    assert intraday.json()["data"] == []


def _cleanup_payload(date_value: str, **overrides):
    payload = {
        "date": date_value,
        "delete_selections": True,
        "delete_daily_quotes": True,
        "delete_intraday_quotes": True,
        "confirm": True,
    }
    payload.update(overrides)
    return payload


def _seed_trade_date_cleanup_data(code: str, date_value: str, next_date: str) -> None:
    db.save_selections([
        {"code": code, "name": "清理测试", "trade_date": date_value, "score": 80},
        {"code": code, "name": "清理测试", "trade_date": next_date, "score": 81},
    ])
    db.save_daily_quotes([
        {"code": code, "name": "清理测试", "trade_date": date_value,
         "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"code": code, "name": "清理测试", "trade_date": next_date,
         "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 200},
    ])
    db.save_intraday_quotes([
        {"code": code, "name": "清理测试", "interval": "30m",
         "trade_datetime": datetime.fromisoformat(f"{date_value}T09:30:00"),
         "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100,
         "amount": None, "amount_estimated": True},
        {"code": code, "name": "清理测试", "interval": "30m",
         "trade_datetime": datetime.fromisoformat(f"{next_date}T09:30:00"),
         "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 200,
         "amount": None, "amount_estimated": True},
    ])


def test_trade_date_cleanup_requires_token_and_all_explicit_confirmations(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    date_value = "2031-02-03"
    with TestClient(app) as client:
        assert client.request("DELETE", "/api/data/trade-date", json=_cleanup_payload(date_value)).status_code == 401
        headers = {"X-Job-Token": "ci-secret"}
        for payload in (
            {"date": date_value},
            _cleanup_payload(date_value, confirm=False),
            _cleanup_payload(date_value, delete_daily_quotes=False),
            _cleanup_payload("20310203"),
        ):
            assert client.request("DELETE", "/api/data/trade-date", json=payload, headers=headers).status_code == 422


def test_trade_date_cleanup_deletes_only_the_confirmed_date_and_preserves_stocks(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    code, date_value, next_date = "300951", "2031-02-03", "2031-02-04"
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app) as client:
        _seed_trade_date_cleanup_data(code, date_value, next_date)
        response = client.request("DELETE", "/api/data/trade-date", json=_cleanup_payload(date_value), headers=headers)
        cleared_selections = client.get(f"/api/selections?date={date_value}")
        retained_selections = client.get(f"/api/selections?date={next_date}")
        daily = client.get(f"/api/stock/{code}/kline?period=daily")
        intraday = client.get(f"/api/stock/{code}/kline?period=30m")
        stocks = client.get("/api/stocks?size=100")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "date": date_value,
        "selection_results_deleted": 1,
        "daily_quotes_deleted": 1,
        "intraday_quotes_deleted": 1,
    }
    assert cleared_selections.json()["data"]["count"] == 0
    assert retained_selections.json()["data"]["count"] == 1
    assert daily.json()["data"] == [[next_date, 11.0, 11.5, 10.0, 12.0, 200.0]]
    assert intraday.json()["data"] == [[f"{next_date}T09:30:00+08:00", 11.0, 11.5, 10.0, 12.0, 200.0]]
    assert code in {item["code"] for item in stocks.json()["data"]["items"]}


def test_trade_date_cleanup_rolls_back_all_deletes_on_failure(monkeypatch):
    monkeypatch.setenv("JOB_API_TOKEN", "ci-secret")
    code, date_value, next_date = "300952", "2031-02-05", "2031-02-06"
    _seed_trade_date_cleanup_data(code, date_value, next_date)
    original_delete = db_compat.delete
    calls = 0

    def fail_second_delete(model):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced delete failure")
        return original_delete(model)

    monkeypatch.setattr(db_compat, "delete", fail_second_delete)
    headers = {"X-Job-Token": "ci-secret"}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request("DELETE", "/api/data/trade-date", json=_cleanup_payload(date_value), headers=headers)
        selections = client.get(f"/api/selections?date={date_value}")
        daily = client.get(f"/api/stock/{code}/kline?period=daily")
        intraday = client.get(f"/api/stock/{code}/kline?period=30m")
    assert response.status_code == 500
    assert selections.json()["data"]["count"] == 1
    assert daily.json()["data"][0][0] == date_value
    assert intraday.json()["data"][0][0] == f"{date_value}T09:30:00+08:00"
