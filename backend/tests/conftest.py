from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkstemp


_descriptor, _database_path = mkstemp(prefix="xuangu-pytest-", suffix=".db")
os.close(_descriptor)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_database_path).as_posix()}"
os.environ["ENABLE_SCHEDULER"] = "false"


def pytest_sessionfinish() -> None:
    from app.db.session import engine

    engine.dispose()
    Path(_database_path).unlink(missing_ok=True)
