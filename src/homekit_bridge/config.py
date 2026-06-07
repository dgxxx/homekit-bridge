import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from homekit_bridge.models import HKType

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS mappings (
    address  TEXT PRIMARY KEY,
    exported INTEGER NOT NULL DEFAULT 0,
    hk_type  TEXT,
    name     TEXT NOT NULL DEFAULT ''
)
"""

_UPSERT = """
INSERT INTO mappings (address, exported, hk_type, name)
VALUES (?, ?, ?, ?)
ON CONFLICT(address) DO UPDATE SET
    exported = excluded.exported,
    hk_type  = excluded.hk_type,
    name     = excluded.name
"""


def _deserialize_hk_type(value: Optional[str]) -> Optional[HKType]:
    if value is None:
        return None
    return HKType(value)


def _serialize_hk_type(hk_type: Optional[HKType]) -> Optional[str]:
    if hk_type is None:
        return None
    return hk_type.value


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "address": row["address"],
        "exported": bool(row["exported"]),
        "hk_type": _deserialize_hk_type(row["hk_type"]),
        "name": row["name"],
    }


class ConfigStore:
    """SQLite-backed persistent mapping store.

    Thread-safe via a shared connection guarded by a lock
    (check_same_thread=False + explicit lock).
    """

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()

    def set_mapping(
        self,
        address: str,
        *,
        exported: bool,
        hk_type: Optional[HKType],
        name: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                _UPSERT,
                (address, int(exported), _serialize_hk_type(hk_type), name),
            )
            self._conn.commit()

    def get_mapping(self, address: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mappings WHERE address = ?", (address,)
            ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)

    def list_exported(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mappings WHERE exported = 1 ORDER BY address"
            ).fetchall()
        return [_row_to_dict(row) for row in rows]
