from __future__ import annotations

from datetime import date, datetime
from threading import Lock

from . import db
from .data.market_data import latest_trading_date, sync_quote_history
from .strategy.engine import run_selection

_lock = Lock()
_quote_lock = Lock()


def execute_quote_sync(trade_date: str | None = None) -> dict:
    """Backfill Tencent qfq bars before a selection run needs them."""
    target = trade_date or latest_trading_date()
    if not _quote_lock.acquire(blocking=False):
        return {"status": "running", "trade_date": target, "message": "已有行情同步任务正在运行"}
    try:
        rows = sync_quote_history(target, universe=db.read_stock_universe() or None)
        saved = db.save_daily_quotes(rows)
        return {"status": "success", "trade_date": target, "result_count": saved}
    except Exception as exc:
        return {"status": "failed", "trade_date": target, "error": str(exc)}
    finally:
        _quote_lock.release()


def execute_selection(trade_date: str | None = None) -> dict:
    trade_date = trade_date or date.today().isoformat()
    if not _lock.acquire(blocking=False):
        return {"status": "running", "trade_date": trade_date, "message": "已有选股任务正在运行"}
    started = datetime.now().isoformat()
    try:
        if not db.has_daily_quotes(trade_date):
            sync_result = execute_quote_sync(trade_date)
            if sync_result["status"] != "success":
                raise RuntimeError(sync_result.get("error") or "行情同步未完成")
        results = run_selection(trade_date)
        db.save_selections(results)
        db.save_job("success", trade_date, started, datetime.now().isoformat(), len(results))
        return {"status": "success", "trade_date": trade_date, "result_count": len(results)}
    except Exception as exc:
        db.save_job("failed", trade_date, started, datetime.now().isoformat(), 0, str(exc))
        return {"status": "failed", "trade_date": trade_date, "error": str(exc)}
    finally:
        _lock.release()
