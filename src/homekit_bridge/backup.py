"""Configuration backup helpers.

Three concerns, kept small and individually testable:

- :func:`write_backup_file` — serialize ``ConfigStore`` to a timestamped JSON
  file under a backup directory.
- :func:`prune_backups` / :func:`list_backups` — rotation + listing.
- :class:`BackupScheduler` — a daemon thread that writes one backup per day
  (skipping days that already have one) and prunes old snapshots.

File names are ``config-YYYYMMDD-HHMMSS.json`` so a plain lexicographic sort is
also chronological.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BACKUP_GLOB = "config-*.json"
_FILENAME_FMT = "config-%Y%m%d-%H%M%S.json"
_DAY_FMT = "%Y%m%d"
_INTERVAL_S = 24 * 60 * 60


def write_backup_file(
    store: Any, backup_dir: Path | str, *, now: Optional[datetime] = None
) -> Path:
    """Write ``store.export_config()`` as a timestamped JSON file. Returns it."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime(_FILENAME_FMT)
    path = backup_dir / stamp
    payload = json.dumps(store.export_config(), indent=2, ensure_ascii=False)
    path.write_text(payload, encoding="utf-8")
    return path


def prune_backups(backup_dir: Path | str, keep: int) -> list[Path]:
    """Delete all but the *keep* newest backups. Returns the deleted paths."""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    files = sorted(backup_dir.glob(_BACKUP_GLOB))  # lexicographic == chronological
    keep = max(0, keep)
    to_delete = files[:-keep] if keep else list(files)
    deleted: list[Path] = []
    for f in to_delete:
        try:
            f.unlink()
            deleted.append(f)
        except OSError:
            logger.warning("Could not delete old backup %s", f)
    return deleted


def list_backups(backup_dir: Path | str) -> list[dict[str, Any]]:
    """Return ``[{name, size, mtime}]`` for all backups, newest first."""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(backup_dir.glob(_BACKUP_GLOB), reverse=True):
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({"name": f.name, "size": st.st_size, "mtime": st.st_mtime})
    return out


class BackupScheduler:
    """Writes one config backup per calendar day and prunes old ones.

    Runs on a daemon thread; ``stop_event`` (shared with the app) breaks the
    sleep for a clean shutdown. ``run_once`` is idempotent per day — it skips
    writing if a backup for today already exists, so frequent restarts don't
    accumulate near-duplicate files.
    """

    def __init__(
        self,
        store: Any,
        backup_dir: Path | str,
        *,
        retention: int = 14,
        interval_s: float = _INTERVAL_S,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self._store = store
        self._backup_dir = Path(backup_dir)
        self._retention = retention
        self._interval_s = interval_s
        self._stop = stop_event or threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run_once(self, *, force: bool = False) -> Optional[Path]:
        """Write today's backup (unless one exists) and prune. Returns the path."""
        if not force and self._has_backup_for_today():
            return None
        path = write_backup_file(self._store, self._backup_dir)
        prune_backups(self._backup_dir, self._retention)
        return path

    def _has_backup_for_today(self) -> bool:
        today = datetime.now().strftime(_DAY_FMT)
        return any(self._backup_dir.glob(f"config-{today}-*.json"))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                path = self.run_once()
                if path is not None:
                    logger.info("Wrote config backup %s", path.name)
            except Exception:
                logger.exception("Config backup failed")
            self._stop.wait(self._interval_s)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="backup-scheduler", daemon=True
        )
        self._thread.start()
