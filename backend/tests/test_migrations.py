from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_intraday_quotes_for_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
    }
    backend_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "app.db.init_db"],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    inspector = inspect(create_engine(environment["DATABASE_URL"]))
    assert "intraday_quotes" in inspector.get_table_names()
    assert "ix_intraday_quotes_stock_interval_datetime" in {
        index["name"] for index in inspector.get_indexes("intraday_quotes")
    }
    assert {
        "stock_code", "interval", "trade_datetime", "open", "high", "low", "close", "volume", "amount", "amount_estimated",
    } <= {column["name"] for column in inspector.get_columns("intraday_quotes")}
