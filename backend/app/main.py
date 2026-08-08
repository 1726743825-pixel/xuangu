from __future__ import annotations

import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api.routes import router as api_router
from .jobs import execute_quote_sync, execute_selection

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _cors_origins() -> list[str]:
    configured = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if _enabled("ENABLE_SCHEDULER") and not scheduler.running:
        scheduler.add_job(
            execute_quote_sync, "cron",
            hour=int(os.getenv("QUOTE_SYNC_HOUR", "15")),
            minute=int(os.getenv("QUOTE_SYNC_MINUTE", "0")),
            id="daily-quote-sync", replace_existing=True,
        )
        scheduler.add_job(
            execute_selection, "cron",
            hour=int(os.getenv("SELECTION_RUN_HOUR", "15")),
            minute=int(os.getenv("SELECTION_RUN_MINUTE", "30")),
            id="daily-selection", replace_existing=True,
        )
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="选股每日选股台 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.status_code, "data": None, "message": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": 422, "data": None, "message": str(exc.errors())})


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"code": 500, "data": None, "message": str(exc)})
