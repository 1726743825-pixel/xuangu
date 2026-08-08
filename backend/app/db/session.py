from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    configured_path = Path(os.getenv("DATABASE_PATH", str(BACKEND_ROOT / "data" / "xuangu.db")))
    if not configured_path.is_absolute():
        configured_path = BACKEND_ROOT / configured_path
    configured_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{configured_path.as_posix()}"


DATABASE_URL = _database_url()
_is_sqlite = DATABASE_URL.startswith("sqlite")
_engine_options: dict = {"pool_pre_ping": True}
if _is_sqlite:
    _engine_options["connect_args"] = {"check_same_thread": False}
if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
    _engine_options["poolclass"] = StaticPool
elif _is_sqlite:
    _engine_options.update(
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    )

engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
