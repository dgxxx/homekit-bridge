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
