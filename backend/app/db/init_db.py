from __future__ import annotations

from .migration_runner import upgrade_database


def main() -> None:
    upgrade_database()


if __name__ == "__main__":
    main()
