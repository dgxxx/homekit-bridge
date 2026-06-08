"""Tests for HomeKitBridge wiring.

Uses a real AccessoryDriver(port=0) and fake CCU3 adapter / config store.
"""

import pytest
from pyhap.accessory_driver import AccessoryDriver

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.hap.bridge import HomeKitBridge
from homekit_bridge.models import HKType, PVData


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCcu3Adapter:
    def __init__(self):
        self.set_calls: list[tuple] = []

    def set_value(self, address: str, key: str, value) -> None:
        self.set_calls.append((address, key, value))

    def list_devices(self):
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def driver(tmp_path):
    drv = AccessoryDriver(port=0, persist_file=str(tmp_path / "bridge.state"))
    yield drv
    drv.stop()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "bridge.db")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def ccu3():
    return FakeCcu3Adapter()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_adds_exported_accessories(driver, store, bus, ccu3):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    store.set_mapping("OEQ2:1", exported=True, hk_type=HKType.OUTLET, name="Plug")
    store.set_mapping("OEQ3:1", exported=False, hk_type=HKType.SWITCH, name="Hidden")

    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    # Bridge should have exactly two accessories (the exported ones)
    assert len(bridge.accessories) == 2


def test_build_skips_unknown_hk_type(driver, store, bus, ccu3):
    store.set_mapping("OEQ1:1", exported=True, hk_type=None, name="NoType")
    # Channel with no hk_type and unresolvable auto type should be skipped
    # (or handle gracefully — no crash is the key requirement)
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()  # must not raise
    # The channel had hk_type=None so it may be skipped
    assert len(bridge.accessories) == 0


def test_ccu3_state_event_updates_accessory(driver, store, bus, ccu3):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")

    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    # Publish a state event — the switch accessory should pick it up
    bus.publish("ccu3.state", {"address": "OEQ1:1", "key": "STATE", "value": True})

    acc = bridge.accessories[0]
    char = acc.get_service("Switch").get_characteristic("On")
    assert char.value is True


def test_homekit_set_calls_ccu3_adapter(driver, store, bus, ccu3):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")

    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    # Simulate a HomeKit SET (as if a user toggled the switch)
    acc = bridge.accessories[0]
    char = acc.get_service("Switch").get_characteristic("On")
    char.client_update_value(True)

    # The adapter's set_value must have been called
    assert len(ccu3.set_calls) == 1
    address, key, value = ccu3.set_calls[0]
    assert address == "OEQ1:1"
    assert value is True


def test_solaredge_event_updates_pv_accessories(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    pv = PVData(power_w=2000.0, energy_today_kwh=10.0, battery_pct=80, producing=True)
    bus.publish("solaredge.data", pv)

    # Bridge should have built PV accessories and updated them
    pv_acc = bridge.pv_accessories
    assert pv_acc is not None

    # Producing accessory should reflect the producing state
    producing = pv_acc["producing"]
    char = producing.get_service("Switch").get_characteristic("On")
    assert char.value is True


def test_bridge_is_single_bridge_accessory(driver, store, bus, ccu3):
    """All accessories live under a single HAP Bridge (one pairing)."""
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    # The HAP bridge should be an instance of pyhap Bridge
    from pyhap.accessory import Bridge as HAPBridge
    assert isinstance(bridge.hap_bridge, HAPBridge)


def test_event_for_non_exported_address_is_ignored(driver, store, bus, ccu3):
    """Events for addresses not in the bridge must not raise."""
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Should not raise
    bus.publish("ccu3.state", {"address": "UNKNOWN:99", "key": "STATE", "value": True})


def test_build_with_contact_export_registers_accessory(driver, store, bus, ccu3):
    store.set_mapping("0000DD898F35C7:1", exported=True, hk_type=HKType.CONTACT,
                      name="Tür Arbeitszimmer")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()  # must not raise (Bug B)
    assert len(bridge.accessories) == 1
    acc = bridge.accessories[0]
    assert acc.get_service("ContactSensor") is not None


def _sync_reconcile(bridge, driver, monkeypatch):
    """Run reconcile()'s loop-marshalled _apply synchronously and count config_changed.

    NOTE: collapses the web-thread/driver-loop boundary into one thread, so it
    verifies the functional contract but cannot surface cross-thread races by design.
    """
    calls = {"config_changed": 0}
    monkeypatch.setattr(driver.loop, "call_soon_threadsafe",
                        lambda fn, *a: fn(*a))
    monkeypatch.setattr(driver, "config_changed",
                        lambda: calls.__setitem__("config_changed",
                                                  calls["config_changed"] + 1))
    return calls


def test_reconcile_adds_newly_exported_accessory(driver, store, bus, ccu3, monkeypatch):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    assert len(bridge.accessories) == 0

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge.reconcile()

    assert len(bridge.accessories) == 1
    assert calls["config_changed"] == 1


def test_reconcile_removes_unexported_accessory(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    assert len(bridge.accessories) == 1

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=False, hk_type=HKType.SWITCH, name="Lamp")
    bridge.reconcile()

    assert len(bridge.accessories) == 0
    assert calls["config_changed"] == 1


def test_reconcile_replaces_on_hk_type_change(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Dev")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first = bridge.accessories[0]

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.OUTLET, name="Dev")
    bridge.reconcile()

    assert len(bridge.accessories) == 1
    new = bridge.accessories[0]
    assert new is not first
    assert new.get_service("Outlet") is not None
    assert calls["config_changed"] == 1


def test_reconcile_name_only_change_is_noop(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Old")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first = bridge.accessories[0]

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="New")
    bridge.reconcile()

    assert bridge.accessories[0] is first
    assert calls["config_changed"] == 0


def test_reconcile_no_change_does_not_call_config_changed(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    bridge.reconcile()

    assert calls["config_changed"] == 0


def test_config_changed_event_triggers_reconcile(driver, store, bus, ccu3, monkeypatch):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bus.publish("config.changed", {"address": "OEQ1:1"})

    assert len(bridge.accessories) == 1
    assert calls["config_changed"] == 1
