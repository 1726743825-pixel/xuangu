from __future__ import annotations

from datetime import date, datetime
from threading import Lock

from . import db
from .strategy.engine import run_selection

_lock = Lock()


def execute_selection(trade_date: str | None = None) -> dict:
    trade_date = trade_date or date.today().isoformat()
    if not _lock.acquire(blocking=False):
        return {"status": "running", "trade_date": trade_date, "message": "已有选股任务正在运行"}
    started = datetime.now().isoformat()
    try:
        results = run_selection(trade_date)
        db.save_selections(results)
        db.save_job("success", trade_date, started, datetime.now().isoformat(), len(results))
        return {"status": "success", "trade_date": trade_date, "result_count": len(results)}
    except Exception as exc:
        db.save_job("failed", trade_date, started, datetime.now().isoformat(), 0, str(exc))
        return {"status": "failed", "trade_date": trade_date, "error": str(exc)}
    finally:
        _lock.release()
