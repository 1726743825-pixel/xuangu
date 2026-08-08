from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "xuangu.db")))


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stocks (
                code TEXT PRIMARY KEY, name TEXT NOT NULL, industry TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS selection_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL, trade_date TEXT NOT NULL, name TEXT NOT NULL,
                price REAL, change_pct REAL, score REAL, strategy_name TEXT,
                industry TEXT, reasons_json TEXT, indicators_json TEXT,
                UNIQUE(code, trade_date)
            );
            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                price REAL, change_pct REAL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
                title TEXT NOT NULL, source TEXT NOT NULL, published_at TEXT NOT NULL,
                url TEXT, summary TEXT
            );
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
                trade_date TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, result_count INTEGER DEFAULT 0, error TEXT
            );
            """
        )


def save_selections(results: list[dict[str, Any]]) -> None:
    with connection() as conn:
        for item in results:
            conn.execute(
                """INSERT INTO stocks(code,name,industry,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name, industry=excluded.industry, updated_at=excluded.updated_at""",
                (item["code"], item["name"], item.get("industry"), datetime.now().isoformat()),
            )
            conn.execute(
                """INSERT INTO selection_results(code,trade_date,name,price,change_pct,score,strategy_name,industry,reasons_json,indicators_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code,trade_date) DO UPDATE SET name=excluded.name, price=excluded.price,
                change_pct=excluded.change_pct, score=excluded.score, strategy_name=excluded.strategy_name,
                industry=excluded.industry, reasons_json=excluded.reasons_json, indicators_json=excluded.indicators_json""",
                (item["code"], item["trade_date"], item["name"], item.get("price"), item.get("change_pct"),
                 item.get("score"), item.get("strategy_name"), item.get("industry"),
                 json.dumps(item.get("reasons", []), ensure_ascii=False),
                 json.dumps(item.get("indicators", {}), ensure_ascii=False)),
            )


def read_selections(trade_date: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM selection_results WHERE trade_date=? ORDER BY score DESC", (trade_date,)).fetchall()
    return [_selection_row(row) for row in rows]


def read_selection(code: str, trade_date: str | None = None) -> dict[str, Any] | None:
    with connection() as conn:
        if trade_date:
            row = conn.execute("SELECT * FROM selection_results WHERE code=? AND trade_date=?", (code, trade_date)).fetchone()
        else:
            row = conn.execute("SELECT * FROM selection_results WHERE code=? ORDER BY trade_date DESC LIMIT 1", (code,)).fetchone()
    return _selection_row(row) if row else None


def _selection_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
    item["indicators"] = json.loads(item.pop("indicators_json") or "{}")
    item.pop("id", None)
    return item


def save_job(status: str, trade_date: str, started_at: str, finished_at: str | None = None, result_count: int = 0, error: str | None = None) -> int:
    with connection() as conn:
        cur = conn.execute("INSERT INTO job_runs(status,trade_date,started_at,finished_at,result_count,error) VALUES(?,?,?,?,?,?)", (status, trade_date, started_at, finished_at, result_count, error))
        return int(cur.lastrowid)


def latest_job() -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
