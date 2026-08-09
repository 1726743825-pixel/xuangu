from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


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
    assert {"selection_price", "selection_price_date"} <= {
        column["name"] for column in inspector.get_columns("selection_results")
    }
    assert {"stock_quote_snapshots", "market_snapshots"} <= set(inspector.get_table_names())
    assert "ix_stock_quote_snapshots_as_of" in {
        index["name"] for index in inspector.get_indexes("stock_quote_snapshots")
    }
    assert "ix_market_snapshots_as_of" in {
        index["name"] for index in inspector.get_indexes("market_snapshots")
    }


def test_snapshot_migration_preserves_existing_volume_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-volume.db"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
    backend_root = Path(__file__).resolve().parents[1]
    alembic_command = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade"]

    subprocess.run(
        [*alembic_command, "20260809_0003"], cwd=backend_root, env=environment, check=True,
        capture_output=True, text=True,
    )
    engine = create_engine(environment["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO stocks (code,name,is_st) VALUES ('600000','迁移保留',0)"
        ))
        connection.execute(
            text(
                "INSERT INTO selection_results "
                "(stock_code,trade_date,strategy_name,signals,score) VALUES "
                "('600000','2026-08-08','迁移测试',:signals,88)"
            ),
            {"signals": '{"price":12.3}'},
        )

    subprocess.run(
        [*alembic_command, "head"], cwd=backend_root, env=environment, check=True,
        capture_output=True, text=True,
    )
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT stock_code, strategy_name, selection_price, selection_price_date "
            "FROM selection_results WHERE stock_code='600000'"
        )).one()
    assert row.stock_code == "600000"
    assert row.strategy_name == "迁移测试"
    assert row.selection_price is None
    assert row.selection_price_date is None


def test_startup_adopts_unversioned_metadata_volume(tmp_path: Path) -> None:
    database_path = tmp_path / "unversioned-volume.db"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
    backend_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "20260809_0003"],
        cwd=backend_root, env=environment, check=True, capture_output=True, text=True,
    )
    engine = create_engine(environment["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO stocks (code,name,is_st) VALUES ('600001','无版本卷',0)"
        ))
        connection.execute(text("DROP TABLE alembic_version"))

    subprocess.run(
        [sys.executable, "-m", "app.db.init_db"], cwd=backend_root, env=environment,
        check=True, capture_output=True, text=True,
    )
    inspector = inspect(engine)
    assert {"stock_quote_snapshots", "market_snapshots"} <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM stocks WHERE code='600001'")) == "无版本卷"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260809_0004"
