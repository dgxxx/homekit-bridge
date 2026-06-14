import json
import threading
from datetime import datetime

from homekit_bridge.backup import (
    BackupScheduler,
    list_backups,
    prune_backups,
    write_backup_file,
)
from homekit_bridge.config import ConfigStore
from homekit_bridge.models import HKType


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    store.get_or_create_aid("A:1")
    return store


def test_write_backup_file_writes_valid_json(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    path = write_backup_file(store, backup_dir)
    assert path.parent == backup_dir
    assert path.name.startswith("config-") and path.name.endswith(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == store.export_config()


def test_prune_backups_keeps_newest(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    # Six snapshots with increasing, lexicographically-sortable timestamps.
    for i in range(6):
        write_backup_file(store, backup_dir, now=datetime(2026, 6, 1 + i, 3, 0, 0))
    deleted = prune_backups(backup_dir, keep=3)
    remaining = sorted(p.name for p in backup_dir.glob("config-*.json"))
    assert len(remaining) == 3
    assert len(deleted) == 3
    # The three newest dates survive.
    assert remaining == [
        "config-20260604-030000.json",
        "config-20260605-030000.json",
        "config-20260606-030000.json",
    ]


def test_list_backups_newest_first(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    write_backup_file(store, backup_dir, now=datetime(2026, 6, 1, 3, 0, 0))
    write_backup_file(store, backup_dir, now=datetime(2026, 6, 2, 3, 0, 0))
    listed = list_backups(backup_dir)
    assert [b["name"] for b in listed] == [
        "config-20260602-030000.json",
        "config-20260601-030000.json",
    ]
    assert all("size" in b and "mtime" in b for b in listed)


def test_list_backups_missing_dir_is_empty(tmp_path):
    assert list_backups(tmp_path / "nope") == []


def test_scheduler_run_once_creates_then_skips_same_day(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    sched = BackupScheduler(store, backup_dir, retention=14)
    first = sched.run_once()
    assert first is not None and first.is_file()
    # A second run on the same day must be a no-op (one backup per day).
    second = sched.run_once()
    assert second is None
    assert len(list(backup_dir.glob("config-*.json"))) == 1


def test_scheduler_run_once_force_always_writes(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    sched = BackupScheduler(store, backup_dir)
    sched.run_once(force=True)
    sched.run_once(force=True)
    assert len(list(backup_dir.glob("config-*.json"))) >= 1


def test_scheduler_thread_writes_then_stops_cleanly(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    stop = threading.Event()
    # Small interval; run_once is per-day idempotent so only one file appears.
    sched = BackupScheduler(store, backup_dir, interval_s=0.05, stop_event=stop)
    sched.start()
    # Wait (briefly) for the first iteration to write the backup.
    deadline = 2.0
    while deadline > 0 and not list(backup_dir.glob("config-*.json")):
        threading.Event().wait(0.02)
        deadline -= 0.02
    assert len(list(backup_dir.glob("config-*.json"))) == 1
    stop.set()
    sched._thread.join(timeout=2)
    assert not sched._thread.is_alive()
