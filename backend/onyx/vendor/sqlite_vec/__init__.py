from __future__ import annotations

import sqlite3
from pathlib import Path

__version__ = "0.1.6"


def loadable_path() -> str:
    return str((Path(__file__).parent / "vec0").resolve())


def load(conn: sqlite3.Connection) -> None:
    conn.load_extension(loadable_path())
