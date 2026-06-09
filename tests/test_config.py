from homekit_bridge.config import ConfigStore
from homekit_bridge.models import HKType


def test_upsert_and_get_channel(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.LIGHTBULB, name="Lamp")
    m = store.get_mapping("OEQ1:1")
    assert m["exported"] is True and m["hk_type"] == HKType.LIGHTBULB and m["name"] == "Lamp"


def test_list_exported(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="A")
    store.set_mapping("B:1", exported=False, hk_type=None, name="B")
    assert [m["address"] for m in store.list_exported()] == ["A:1"]


def test_upsert_updates_existing(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="Original")
    store.set_mapping("A:1", exported=True, hk_type=HKType.OUTLET, name="Updated")
    m = store.get_mapping("A:1")
    assert m["name"] == "Updated" and m["hk_type"] == HKType.OUTLET


def test_get_missing_returns_none(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    assert store.get_mapping("nonexistent:1") is None


def test_hktype_none_serializes_and_deserializes(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("Z:1", exported=False, hk_type=None, name="NoType")
    m = store.get_mapping("Z:1")
    assert m["hk_type"] is None


def test_unknown_hktype_in_db_returns_none(tmp_path):
    """A stale or manually-edited DB value that is not a valid HKType should
    not crash the application — it must be silently treated as None."""
    store = ConfigStore(tmp_path / "c.db")
    # Write a value directly to the DB that is not a valid HKType
    with store._lock:
        store._conn.execute(
            "INSERT INTO mappings (address, exported, hk_type, name) VALUES (?, ?, ?, ?)",
            ("BAD:1", 1, "no_longer_valid_type", "Stale"),
        )
        store._conn.commit()
    m = store.get_mapping("BAD:1")
    assert m is not None
    assert m["hk_type"] is None   # unknown value → None, not ValueError


# ---------------------------------------------------------------------------
# AID persistence — HomeKit accessory IDs must stay stable per address
# ---------------------------------------------------------------------------

def test_aid_allocation_starts_at_2_and_increments(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    assert store.get_or_create_aid("A:1") == 2
    assert store.get_or_create_aid("B:1") == 3


def test_aid_is_stable_for_same_address(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    first = store.get_or_create_aid("A:1")
    store.get_or_create_aid("B:1")
    assert store.get_or_create_aid("A:1") == first


def test_aid_skips_7(tmp_path):
    # pyhap quirk: AID 7 is unsupported (HAP-python issue #61)
    store = ConfigStore(tmp_path / "c.db")
    aids = [store.get_or_create_aid(f"D{i}:1") for i in range(7)]
    assert aids == [2, 3, 4, 5, 6, 8, 9]


def test_aid_persists_across_reopen(tmp_path):
    db = tmp_path / "c.db"
    store = ConfigStore(db)
    aid_a = store.get_or_create_aid("A:1")
    aid_b = store.get_or_create_aid("B:1")
    reopened = ConfigStore(db)
    assert reopened.get_or_create_aid("A:1") == aid_a
    assert reopened.get_or_create_aid("B:1") == aid_b
