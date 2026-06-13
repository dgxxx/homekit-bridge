"""Tests for HAP accessory factories.

All tests use AccessoryDriver(port=0) to avoid binding real network sockets.
"""

import pytest
from pyhap.accessory_driver import AccessoryDriver

from homekit_bridge.hap.accessories import (
    make_accessory,
    SwitchAccessory,
    OutletAccessory,
    LightbulbAccessory,
    CoverAccessory,
    ThermostatAccessory,
    ContactSensorAccessory,
    WindowAccessory,
    DoorAccessory,
    TemperatureSensorAccessory,
    HumiditySensorAccessory,
    MotionSensorAccessory,
    LightSensorAccessory,
    EvePowerAccessory,
    BatteryAccessory,
    ProducingAccessory,
)


# ---------------------------------------------------------------------------
# Shared driver fixture — one driver per test module is fine; the driver
# doesn't actually start (no start() call), so port=0 is safe.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    p = tmp_path_factory.mktemp("hap") / "test.state"
    drv = AccessoryDriver(port=0, persist_file=str(p))
    yield drv
    drv.stop()


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

def test_switch_update_state(driver):
    acc = SwitchAccessory(driver, "TestSwitch2")
    acc.update_state(True)
    char = acc.get_service("Switch").get_characteristic("On")
    assert char.value is True


# ---------------------------------------------------------------------------
# Outlet
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Lightbulb
# ---------------------------------------------------------------------------

def test_lightbulb_update_state(driver):
    acc = LightbulbAccessory(driver, "TestBulb2")
    acc.update_state(on=True, brightness=80)
    svc = acc.get_service("Lightbulb")
    assert svc.get_characteristic("On").value is True
    assert svc.get_characteristic("Brightness").value == 80


# ---------------------------------------------------------------------------
# Cover (WindowCovering)
# ---------------------------------------------------------------------------

def test_cover_update_state(driver):
    acc = CoverAccessory(driver, "TestCover3")
    acc.update_state(current_position=50, target_position=50)
    svc = acc.get_service("WindowCovering")
    assert svc.get_characteristic("CurrentPosition").value == 50


# ---------------------------------------------------------------------------
# Thermostat
# ---------------------------------------------------------------------------

def test_thermostat_update_state(driver):
    acc = ThermostatAccessory(driver, "TestThermo2")
    acc.update_state(current_temp=20.0, target_temp=22.0)
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("CurrentTemperature").value == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# ContactSensor
# ---------------------------------------------------------------------------

def test_contact_sensor_update_state(driver):
    acc = ContactSensorAccessory(driver, "TestContact")
    acc.update_state(contact_detected=True)
    char = acc.get_service("ContactSensor").get_characteristic("ContactSensorState")
    # ContactSensorState: 0 = contact detected, 1 = not detected
    assert char.value == 0


def test_contact_sensor_not_detected(driver):
    acc = ContactSensorAccessory(driver, "TestContact2")
    acc.update_state(contact_detected=False)
    char = acc.get_service("ContactSensor").get_characteristic("ContactSensorState")
    assert char.value == 1


# ---------------------------------------------------------------------------
# Window / Door (position-based contact, shown as a room tile)
# ---------------------------------------------------------------------------

def test_window_open_sets_full_position(driver):
    acc = WindowAccessory(driver, "TestWindow")
    acc.update_state(open=True)
    svc = acc.get_service("Window")
    assert svc.get_characteristic("CurrentPosition").value == 100
    assert svc.get_characteristic("TargetPosition").value == 100
    assert svc.get_characteristic("PositionState").value == 2  # stopped
    assert acc.display_state() == {"open": True}


def test_window_closed_sets_zero_position(driver):
    acc = WindowAccessory(driver, "TestWindow2")
    acc.update_state(open=False)
    svc = acc.get_service("Window")
    assert svc.get_characteristic("CurrentPosition").value == 0
    assert svc.get_characteristic("TargetPosition").value == 0
    assert acc.display_state() == {"open": False}


def test_door_open_sets_full_position(driver):
    acc = DoorAccessory(driver, "TestDoor")
    acc.update_state(open=True)
    svc = acc.get_service("Door")
    assert svc.get_characteristic("CurrentPosition").value == 100
    assert acc.display_state() == {"open": True}


def test_window_and_door_are_read_only(driver):
    # Read-only: no writable characteristics wired, so HomeKit writes never
    # reach the device (the next state event re-syncs the position).
    win = WindowAccessory(driver, "TestWindowRO")
    door = DoorAccessory(driver, "TestDoorRO")
    assert getattr(win, "writable_characteristics", None) is None
    assert getattr(door, "writable_characteristics", None) is None


# ---------------------------------------------------------------------------
# TemperatureSensor
# ---------------------------------------------------------------------------

def test_temperature_sensor_update_state(driver):
    acc = TemperatureSensorAccessory(driver, "TestTemp")
    acc.update_state(temperature=23.5)
    char = acc.get_service("TemperatureSensor").get_characteristic("CurrentTemperature")
    assert char.value == pytest.approx(23.5)


# ---------------------------------------------------------------------------
# HumiditySensor
# ---------------------------------------------------------------------------

def test_humidity_sensor_update_state(driver):
    acc = HumiditySensorAccessory(driver, "TestHumidity")
    acc.update_state(humidity=60.0)
    char = acc.get_service("HumiditySensor").get_characteristic("CurrentRelativeHumidity")
    assert char.value == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# MotionSensor
# ---------------------------------------------------------------------------

def test_motion_sensor_update_state(driver):
    acc = MotionSensorAccessory(driver, "TestMotion")
    acc.update_state(motion_detected=True)
    char = acc.get_service("MotionSensor").get_characteristic("MotionDetected")
    assert char.value is True


# ---------------------------------------------------------------------------
# PV: LightSensor
# ---------------------------------------------------------------------------

def test_light_sensor_update_state(driver):
    acc = LightSensorAccessory(driver, "PV-Lux")
    acc.update_state(lux=2450.0)
    char = acc.get_service("LightSensor").get_characteristic("CurrentAmbientLightLevel")
    assert char.value == pytest.approx(2450.0)


# ---------------------------------------------------------------------------
# PV: EvePowerAccessory
# ---------------------------------------------------------------------------

def test_eve_power_update_state(driver):
    acc = EvePowerAccessory(driver, "PV-Power")
    acc.update_state(watts=2450.0, kwh=14.2)
    # Eve Power uses custom characteristics; verify stored values
    assert acc.current_watts == pytest.approx(2450.0)
    assert acc.current_kwh == pytest.approx(14.2)


# ---------------------------------------------------------------------------
# PV: BatteryAccessory
# ---------------------------------------------------------------------------

def test_battery_accessory_update_state(driver):
    acc = BatteryAccessory(driver, "PV-Battery")
    acc.update_state(pct=78)
    char = acc.get_service("BatteryService").get_characteristic("BatteryLevel")
    assert char.value == 78


def test_battery_accessory_none_pct(driver):
    acc = BatteryAccessory(driver, "PV-Battery2")
    # Should not raise when pct is None (battery absent)
    acc.update_state(pct=None)


# ---------------------------------------------------------------------------
# PV: ProducingAccessory
# ---------------------------------------------------------------------------

def test_producing_accessory_update_state_true(driver):
    acc = ProducingAccessory(driver, "PV-Producing")
    acc.update_state(on=True)
    char = acc.get_service("Switch").get_characteristic("On")
    assert char.value is True


def test_producing_accessory_update_state_false(driver):
    acc = ProducingAccessory(driver, "PV-Producing2")
    acc.update_state(on=False)
    char = acc.get_service("Switch").get_characteristic("On")
    assert char.value is False


# ---------------------------------------------------------------------------
# make_accessory factory
# ---------------------------------------------------------------------------

def test_make_accessory_builds_contact_without_on_set(driver):
    from homekit_bridge.hap.accessories import ContactSensorAccessory
    acc = make_accessory(driver=driver, hk_type="contact", name="Door")
    assert isinstance(acc, ContactSensorAccessory)


def test_make_accessory_builds_window(driver):
    acc = make_accessory(driver=driver, hk_type="window", name="Kitchen Window")
    assert isinstance(acc, WindowAccessory)


def test_make_accessory_builds_door(driver):
    acc = make_accessory(driver=driver, hk_type="door", name="Front Door")
    assert isinstance(acc, DoorAccessory)


def test_make_accessory_builds_switch(driver):
    acc = make_accessory(driver=driver, hk_type="switch", name="Lamp")
    assert isinstance(acc, SwitchAccessory)
    assert set(acc.writable_characteristics()) == {"on"}


def test_make_accessory_unknown_type_returns_none(driver):
    assert make_accessory(driver=driver, hk_type="nonsense", name="x") is None


# ---------------------------------------------------------------------------
# writable_characteristics() + thermostat humidity / range
# ---------------------------------------------------------------------------

def test_thermostat_has_humidity_characteristic(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(current_temp=25.0, target_temp=21.0, humidity=40)
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("CurrentTemperature").value == 25.0
    assert svc.get_characteristic("TargetTemperature").value == 21.0
    assert svc.get_characteristic("CurrentRelativeHumidity").value == 40


def test_thermostat_frost_setpoint_maps_to_off(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(target_temp=21.0)
    # HmIP frost protection (4.5 °C) == "off"; the last heat setpoint is kept
    acc.update_state(target_temp=4.5)
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 0
    assert svc.get_characteristic("CurrentHeatingCoolingState").value == 0
    assert svc.get_characteristic("TargetTemperature").value == 21.0


def test_thermostat_normal_setpoint_maps_to_heat(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(target_temp=4.5)
    acc.update_state(target_temp=22.5)
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 1
    assert svc.get_characteristic("CurrentHeatingCoolingState").value == 1
    assert svc.get_characteristic("TargetTemperature").value == 22.5


def test_thermostat_mode_valid_values_off_heat_auto(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    char = acc.get_service("Thermostat").get_characteristic("TargetHeatingCoolingState")
    assert set(char.properties["ValidValues"].values()) == {0, 1, 3}


def test_thermostat_target_temperature_range_is_homekit_compliant(driver):
    # Apple's spec minimum for TargetTemperature is 10 °C; frost setpoints
    # below that are represented as mode "off" instead.
    acc = ThermostatAccessory(driver, "Thermo")
    char = acc.get_service("Thermostat").get_characteristic("TargetTemperature")
    assert char.properties["minValue"] == 10.0


def test_thermostat_writes_for_mode(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(target_temp=22.0)  # establishes the last heating setpoint
    assert acc.writes_for_mode(0) == {"CONTROL_MODE": 1,
                                      "SET_POINT_TEMPERATURE": 4.5}         # Off (forces MANU)
    assert acc.writes_for_mode(3) == {"CONTROL_MODE": 0}                   # Auto
    assert acc.writes_for_mode(1) == {"CONTROL_MODE": 1,
                                      "SET_POINT_TEMPERATURE": 22.0}       # Heat


def test_thermostat_heat_write_before_any_state_uses_target_default(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    # No update_state yet → Heat write uses the characteristic's initial TargetTemperature.
    assert acc.writes_for_mode(1) == {"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": 10.0}


def test_thermostat_auto_mode_maps_to_auto(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(set_point_mode=0)  # HmIP AUTO
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3
    # Current has no "Auto" state in HomeKit → shown as Heat
    assert svc.get_characteristic("CurrentHeatingCoolingState").value == 1


def test_thermostat_mode_derivation_is_order_independent(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    svc = acc.get_service("Thermostat")
    # mode event arrives BEFORE the setpoint event
    acc.update_state(set_point_mode=1)        # MANU
    acc.update_state(target_temp=4.5)         # frost → Off
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 0
    # later the device switches to AUTO
    acc.update_state(set_point_mode=0)
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3
    # and back to MANU with a real setpoint → Heat
    acc.update_state(set_point_mode=1)
    acc.update_state(target_temp=21.0)
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 1


def test_writable_characteristics_per_type(driver):
    assert set(SwitchAccessory(driver, "s").writable_characteristics()) == {"on"}
    assert set(OutletAccessory(driver, "o").writable_characteristics()) == {"on"}
    assert set(LightbulbAccessory(driver, "l").writable_characteristics()) == {"on", "brightness"}
    assert set(CoverAccessory(driver, "c").writable_characteristics()) == {"position"}
    assert set(ThermostatAccessory(driver, "t").writable_characteristics()) == {
        "target_temp", "mode"}


def test_cover_update_state_position_sets_both(driver):
    acc = CoverAccessory(driver, "Blind")
    acc.update_state(position=50.0)
    svc = acc.get_service("WindowCovering")
    assert svc.get_characteristic("CurrentPosition").value == 50.0
    assert svc.get_characteristic("TargetPosition").value == 50.0
