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


def test_control_snapshot_reports_state(driver, store, bus, ccu3):
    store.set_mapping("SW:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    bus.publish("ccu3.state", {"address": "SW:1", "key": "STATE", "value": True})

    snap = bridge.control_snapshot()
    assert len(snap) == 1
    assert snap[0]["address"] == "SW:1"
    assert snap[0]["hk_type"] == "switch"
    assert snap[0]["state"] == {"on": True}


def test_apply_control_routes_through_setter(driver, store, bus, ccu3):
    store.set_mapping("SW:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    assert bridge.apply_control("SW:1", "on", True) is True
    assert ("SW:1", "STATE", True) in ccu3.set_calls

    # Unknown field, unknown address, and read-only accessory all return False.
    assert bridge.apply_control("SW:1", "position", 50) is False
    assert bridge.apply_control("NOPE:1", "on", True) is False


def test_apply_control_cover_scales_position(driver, store, bus, ccu3):
    store.set_mapping("BL:4", exported=True, hk_type=HKType.COVER, name="Rollo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    assert bridge.apply_control("BL:4", "position", 30) is True
    # COVER write scale is 100 → HomeKit 30 % becomes HM LEVEL 0.30
    assert ccu3.set_calls[-1] == ("BL:4", "LEVEL", 0.3)


def test_apply_control_rejects_readonly_contact(driver, store, bus, ccu3):
    store.set_mapping("DC:1", exported=True, hk_type=HKType.CONTACT, name="Tür")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    assert bridge.apply_control("DC:1", "open", False) is False


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


def test_thermostat_routes_datapoints_without_clobber(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Order mirrors the real payload: ACTUAL_TEMPERATURE is NOT last; BOOST_MODE is.
    for k, v in [("ACTUAL_TEMPERATURE", 25.0), ("HUMIDITY", 40),
                 ("SET_POINT_TEMPERATURE", 21.0), ("BOOST_MODE", False)]:
        bus.publish("ccu3.state", {"address": "TH:1", "key": k, "value": v})
    svc = bridge.accessories[0].get_service("Thermostat")
    assert svc.get_characteristic("CurrentTemperature").value == 25.0
    assert svc.get_characteristic("CurrentRelativeHumidity").value == 40
    assert svc.get_characteristic("TargetTemperature").value == 21.0


def test_thermostat_frost_setpoint_event_switches_mode_off(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    svc = bridge.accessories[0].get_service("Thermostat")
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 21.0})
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 4.5})
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 0
    assert svc.get_characteristic("CurrentHeatingCoolingState").value == 0
    assert svc.get_characteristic("TargetTemperature").value == 21.0


def test_thermostat_mode_off_publishes_frost_setpoint(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(0)
    assert ("TH:1", "SET_POINT_TEMPERATURE", 4.5) in ccu3.set_calls
    assert ("TH:1", "CONTROL_MODE", 1) in ccu3.set_calls


def test_thermostat_mode_heat_restores_last_setpoint(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Device was heating at 21.5, then turned off (frost setpoint)
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 21.5})
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 4.5})
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(1)
    assert ("TH:1", "SET_POINT_TEMPERATURE", 21.5) in ccu3.set_calls


def test_thermostat_set_publishes_set_point_temperature(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic("TargetTemperature")
    char.client_update_value(21.0)
    assert ("TH:1", "SET_POINT_TEMPERATURE", 21.0) in ccu3.set_calls


def test_switch_set_publishes_state(driver, store, bus, ccu3):
    store.set_mapping("SW:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Switch").get_characteristic("On")
    char.client_update_value(True)
    assert ("SW:1", "STATE", True) in ccu3.set_calls


def test_cover_level_updates_position(driver, store, bus, ccu3):
    store.set_mapping("CV:1", exported=True, hk_type=HKType.COVER, name="Blind")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    bus.publish("ccu3.state", {"address": "CV:1", "key": "LEVEL", "value": 0.5})
    svc = bridge.accessories[0].get_service("WindowCovering")
    assert svc.get_characteristic("CurrentPosition").value == 50.0
    assert svc.get_characteristic("TargetPosition").value == 50.0


# ---------------------------------------------------------------------------
# AID stability — accessory IDs must survive restarts and new exports
# ---------------------------------------------------------------------------

def _aids_by_name(bridge):
    return {acc.display_name: acc.aid for acc in bridge.accessories}


def test_aids_survive_restart_with_new_device_sorting_first(tmp_path, driver, store, bus, ccu3):
    store.set_mapping("B:1", exported=True, hk_type=HKType.SWITCH, name="B")
    store.set_mapping("C:1", exported=True, hk_type=HKType.OUTLET, name="C")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first_aids = _aids_by_name(bridge)

    # "Restart": new driver + bridge over the same store, with a new export
    # whose address sorts before the existing ones.
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="A")
    driver2 = AccessoryDriver(port=0, persist_file=str(tmp_path / "restart.state"))
    try:
        bridge2 = HomeKitBridge(driver=driver2, config_store=store, ccu3_adapter=ccu3, bus=bus)
        bridge2.build()
        second_aids = _aids_by_name(bridge2)
        assert second_aids["B"] == first_aids["B"]
        assert second_aids["C"] == first_aids["C"]
        # The new device gets a fresh AID, not one of the existing ones
        assert second_aids["A"] not in (first_aids["B"], first_aids["C"])
    finally:
        driver2.stop()


def test_pv_accessory_aids_survive_restart(tmp_path, driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first = {kind: acc.aid for kind, acc in bridge.pv_accessories.items()}

    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="A")
    driver2 = AccessoryDriver(port=0, persist_file=str(tmp_path / "restart.state"))
    try:
        bridge2 = HomeKitBridge(driver=driver2, config_store=store, ccu3_adapter=ccu3, bus=bus)
        bridge2.build()
        second = {kind: acc.aid for kind, acc in bridge2.pv_accessories.items()}
        assert second == first
    finally:
        driver2.stop()


def test_reconcile_added_accessory_keeps_aid_after_restart(
        tmp_path, driver, store, bus, ccu3, monkeypatch):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("NEW:1", exported=True, hk_type=HKType.SWITCH, name="New")
    bridge.reconcile()
    runtime_aid = _aids_by_name(bridge)["New"]

    driver2 = AccessoryDriver(port=0, persist_file=str(tmp_path / "restart.state"))
    try:
        bridge2 = HomeKitBridge(driver=driver2, config_store=store, ccu3_adapter=ccu3, bus=bus)
        bridge2.build()
        assert _aids_by_name(bridge2)["New"] == runtime_aid
    finally:
        driver2.stop()


def test_make_setter_dict_converter_publishes_each_datapoint(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    setter = bridge._make_setter("ADDR", "IGNORED", 1.0, convert=lambda v: {"A": 1, "B": 2})
    setter(99)
    assert ("ADDR", "A", 1) in ccu3.set_calls
    assert ("ADDR", "B", 2) in ccu3.set_calls
    # The declared dp.kwarg ("IGNORED") and the raw value are NOT published for a dict converter
    assert ("ADDR", "IGNORED", 99) not in ccu3.set_calls
    assert len(ccu3.set_calls) == 2


def test_make_setter_scalar_converter_still_scales(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    setter = bridge._make_setter("ADDR", "LEVEL", 100.0, convert=None)
    setter(50)  # scale 100 → 0.5
    assert ("ADDR", "LEVEL", 0.5) in ccu3.set_calls


def test_make_setter_scalar_converter_result_is_scaled(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    setter = bridge._make_setter("ADDR", "K", 2.0, convert=lambda v: v + 1)
    setter(4)  # convert → 5, then / scale 2.0 → 2.5
    assert ("ADDR", "K", 2.5) in ccu3.set_calls


def test_thermostat_auto_mode_event_sets_homekit_auto(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    svc = bridge.accessories[0].get_service("Thermostat")
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_MODE", "value": 0})
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3


def test_thermostat_mode_auto_publishes_control_mode(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(3)  # Auto
    # Mode is set via CONTROL_MODE (the CCU rejects setValue on SET_POINT_MODE).
    assert ("TH:1", "CONTROL_MODE", 0) in ccu3.set_calls


def test_thermostat_mode_heat_publishes_manu_and_setpoint(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Heating at 21.5, then off (frost) — last heating setpoint 21.5 is retained.
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 21.5})
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 4.5})
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(1)  # Heat
    assert ("TH:1", "CONTROL_MODE", 1) in ccu3.set_calls
    assert ("TH:1", "SET_POINT_TEMPERATURE", 21.5) in ccu3.set_calls


# ---------------------------------------------------------------------------
# CCU3 system variable (sysvar) — full path through the real MqttSource
# ---------------------------------------------------------------------------

class _FakeMqttClient:
    def __init__(self):
        self.published: list[tuple] = []
        self.on_connect = None
        self.on_message = None

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, topic):
        pass


def test_sysvar_switch_end_to_end_via_mqttsource(driver, store, bus):
    """A boolean sysvar exported as a Switch: MQTT state drives the On
    characteristic, and a HomeKit toggle publishes to the sysvar set topic."""
    import json

    from homekit_bridge.mqttsource import MqttSource

    src = MqttSource(bus, client=_FakeMqttClient())
    store.set_mapping("sysvar:Kachelofen", exported=True, hk_type=HKType.SWITCH,
                      name="Kachelofen")

    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=src, bus=bus)
    bridge.build()

    # Incoming retained sysvar state → switch turns On
    src.handle("homematic/$sysvar/Kachelofen/state", '{"STATE": true}')
    char = bridge.accessories[0].get_service("Switch").get_characteristic("On")
    assert char.value is True

    # HomeKit toggle Off → publishes {"STATE": false} on the sysvar set topic
    char.client_update_value(False)
    topic, payload, _retain = src._client.published[-1]
    assert topic == "homematic/$sysvar/Kachelofen/set"
    assert json.loads(payload) == {"STATE": False}
