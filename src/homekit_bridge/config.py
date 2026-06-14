import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from homekit_bridge.models import HKType

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS mappings (
    address  TEXT PRIMARY KEY,
    exported INTEGER NOT NULL DEFAULT 0,
    hk_type  TEXT,
    name     TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_AIDS_TABLE = """
CREATE TABLE IF NOT EXISTS aids (
    address TEXT PRIMARY KEY,
    aid     INTEGER NOT NULL UNIQUE
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
    try:
        return HKType(value)
    except ValueError:
        logger.warning("Unknown hk_type value %r in DB — treating as None", value)
        return None


def _serialize_hk_type(hk_type: Optional[HKType]) -> Optional[str]:
    if hk_type is None:
        return None
    return hk_type.value


# Version tag written into every backup payload so a future format change can
# be detected on restore.
BACKUP_VERSION = 1


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
            self._conn.execute(_CREATE_AIDS_TABLE)
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

    def get_or_create_aid(self, address: str) -> int:
        """Return the persistent HomeKit accessory ID for *address*.

        HomeKit requires AIDs to stay stable for the lifetime of a pairing and
        never be reused.  Allocation is monotonic (rows are never deleted),
        starts at 2 (1 is the bridge itself) and skips 7 (unsupported in
        HAP-python, issue #61).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT aid FROM aids WHERE address = ?", (address,)
            ).fetchone()
            if row is not None:
                return row["aid"]
            top = self._conn.execute("SELECT MAX(aid) AS m FROM aids").fetchone()["m"]
            aid = (top or 1) + 1
            if aid == 7:
                aid = 8
            self._conn.execute(
                "INSERT INTO aids (address, aid) VALUES (?, ?)", (address, aid)
            )
            self._conn.commit()
            return aid

    def list_all(self) -> list[dict[str, Any]]:
        """Return every stored mapping (exported and non-exported)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mappings ORDER BY address"
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Backup / restore
    # ------------------------------------------------------------------

    def export_config(self) -> dict[str, Any]:
        """Serialize the full configuration to a JSON-friendly dict.

        Includes every mapping (exported or not) and the persistent AID table,
        so a restore reproduces the exact same HomeKit accessory database without
        forcing a re-pairing. ``hk_type`` is kept as the raw stored string (not
        the ``HKType`` enum) so unknown/stale values round-trip untouched.
        """
        with self._lock:
            mapping_rows = self._conn.execute(
                "SELECT address, exported, hk_type, name FROM mappings ORDER BY address"
            ).fetchall()
            aid_rows = self._conn.execute(
                "SELECT address, aid FROM aids ORDER BY aid"
            ).fetchall()
        return {
            "version": BACKUP_VERSION,
            "mappings": [
                {
                    "address": r["address"],
                    "exported": bool(r["exported"]),
                    "hk_type": r["hk_type"],
                    "name": r["name"],
                }
                for r in mapping_rows
            ],
            "aids": [
                {"address": r["address"], "aid": r["aid"]} for r in aid_rows
            ],
        }

    def import_config(self, data: Any) -> int:
        """Replace the configuration from an :func:`export_config` payload.

        Wipes and re-fills the ``mappings`` table. The ``aids`` table is only
        replaced when the payload carries an ``"aids"`` key (older backups
        without it leave the existing AID allocation untouched). Returns the
        number of mappings imported. Raises ``ValueError`` on a structurally
        invalid payload; the change is atomic (rolled back on any error).
        """
        if not isinstance(data, dict):
            raise ValueError("backup must be a JSON object")

        raw_mappings = data.get("mappings")
        if not isinstance(raw_mappings, list):
            raise ValueError("backup is missing a 'mappings' list")

        mapping_rows: list[tuple[str, int, Optional[str], str]] = []
        for m in raw_mappings:
            if not isinstance(m, dict) or "address" not in m:
                raise ValueError("each mapping needs an 'address'")
            hk_type = m.get("hk_type")
            if hk_type is not None and not isinstance(hk_type, str):
                raise ValueError("'hk_type' must be a string or null")
            mapping_rows.append(
                (
                    str(m["address"]),
                    int(bool(m.get("exported", False))),
                    hk_type,
                    str(m.get("name", "")),
                )
            )

        replace_aids = "aids" in data
        aid_rows: list[tuple[str, int]] = []
        if replace_aids:
            raw_aids = data.get("aids") or []
            if not isinstance(raw_aids, list):
                raise ValueError("'aids' must be a list")
            for a in raw_aids:
                if not isinstance(a, dict) or "address" not in a or "aid" not in a:
                    raise ValueError("each aid entry needs 'address' and 'aid'")
                aid_rows.append((str(a["address"]), int(a["aid"])))

        with self._lock:
            try:
                self._conn.execute("DELETE FROM mappings")
                self._conn.executemany(_UPSERT, mapping_rows)
                if replace_aids:
                    self._conn.execute("DELETE FROM aids")
                    self._conn.executemany(
                        "INSERT INTO aids (address, aid) VALUES (?, ?)", aid_rows
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return len(mapping_rows)
