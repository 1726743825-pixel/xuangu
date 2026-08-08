from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .integrations.market_adapter import get_kline, get_messages, get_quote
from .jobs import execute_selection
from .schemas import RunSelectionRequest

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if not scheduler.running:
        scheduler.add_job(execute_selection, "cron", hour=int(os.getenv("SELECTION_RUN_HOUR", "16")), minute=int(os.getenv("SELECTION_RUN_MINUTE", "0")), id="daily-selection", replace_existing=True)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="选股每日选股台 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "xuangu-api"}


@app.get("/api/selections")
def selections(trade_date: str | None = Query(default=None, alias="date")):
    target = trade_date or date.today().isoformat()
    results = db.read_selections(target)
    return {"date": target, "items": results, "count": len(results)}


@app.get("/api/selections/{code}")
def selection_detail(code: str, trade_date: str | None = Query(default=None, alias="date")):
    item = db.read_selection(code, trade_date)
    if not item:
        raise HTTPException(404, "没有找到该股票的选股记录")
    return item


@app.get("/api/stocks/{code}/quote")
def quote(code: str):
    return get_quote(code)


@app.get("/api/stocks/{code}/kline")
def kline(code: str, days: int = 60):
    return {"code": code, "items": get_kline(code, min(max(days, 10), 240))}


@app.get("/api/stocks/{code}/messages")
def messages(code: str):
    return {"code": code, "items": get_messages(code)}


@app.post("/api/jobs/run-selection")
def run_selection(request: RunSelectionRequest | None = None):
    return execute_selection(request.trade_date if request else None)


@app.get("/api/jobs/latest")
def latest_job():
    return db.latest_job() or {"status": "idle", "message": "还没有运行记录"}
