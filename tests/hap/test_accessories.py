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

def test_switch_on_set_callback(driver):
    received = []
    acc = SwitchAccessory(driver, "TestSwitch", on_set=lambda v: received.append(v))
    # Simulate HomeKit SET On=True
    char = acc.get_service("Switch").get_characteristic("On")
    char.client_update_value(True)
    assert received == [True]


def test_switch_update_state(driver):
    acc = SwitchAccessory(driver, "TestSwitch2")
    acc.update_state(True)
    char = acc.get_service("Switch").get_characteristic("On")
    assert char.value is True


# ---------------------------------------------------------------------------
# Outlet
# ---------------------------------------------------------------------------

def test_outlet_on_set_callback(driver):
    received = []
    acc = OutletAccessory(driver, "TestOutlet", on_set=lambda v: received.append(v))
    char = acc.get_service("Outlet").get_characteristic("On")
    char.client_update_value(True)
    assert received == [True]


# ---------------------------------------------------------------------------
# Lightbulb
# ---------------------------------------------------------------------------

def test_lightbulb_on_set_callback(driver):
    received = []
    acc = LightbulbAccessory(driver, "TestBulb", on_set=lambda v: received.append(v))
    char = acc.get_service("Lightbulb").get_characteristic("On")
    char.client_update_value(False)
    assert received == [False]


def test_lightbulb_update_state(driver):
    acc = LightbulbAccessory(driver, "TestBulb2")
    acc.update_state(on=True, brightness=80)
    svc = acc.get_service("Lightbulb")
    assert svc.get_characteristic("On").value is True
    assert svc.get_characteristic("Brightness").value == 80


# ---------------------------------------------------------------------------
# Cover (WindowCovering)
# ---------------------------------------------------------------------------

def test_cover_target_position_callback(driver):
    received = []
    acc = CoverAccessory(driver, "TestCover", on_set=lambda v: received.append(v))
    char = acc.get_service("WindowCovering").get_characteristic("TargetPosition")
    char.client_update_value(75)
    assert received == [75]


def test_cover_position_range(driver):
    received = []
    acc = CoverAccessory(driver, "TestCover2", on_set=lambda v: received.append(v))
    char = acc.get_service("WindowCovering").get_characteristic("TargetPosition")
    char.client_update_value(0)
    char.client_update_value(100)
    assert received == [0, 100]


def test_cover_update_state(driver):
    acc = CoverAccessory(driver, "TestCover3")
    acc.update_state(current_position=50, target_position=50)
    svc = acc.get_service("WindowCovering")
    assert svc.get_characteristic("CurrentPosition").value == 50


# ---------------------------------------------------------------------------
# Thermostat
# ---------------------------------------------------------------------------

def test_thermostat_target_temp_callback(driver):
    received = []
    acc = ThermostatAccessory(driver, "TestThermo", on_set=lambda v: received.append(v))
    char = acc.get_service("Thermostat").get_characteristic("TargetTemperature")
    char.client_update_value(21.5)
    assert received == [pytest.approx(21.5)]


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
# make_accessory factory — on_set handling
# ---------------------------------------------------------------------------

def test_make_accessory_sensor_ignores_on_set(driver):
    # Read-only sensors don't accept on_set; passing it must NOT raise.
    acc = make_accessory(driver=driver, hk_type="contact", name="Door", on_set=lambda v: None)
    assert isinstance(acc, ContactSensorAccessory)


def test_make_accessory_switch_wires_on_set(driver):
    received = []
    acc = make_accessory(
        driver=driver, hk_type="switch", name="Lamp", on_set=lambda v: received.append(v)
    )
    assert isinstance(acc, SwitchAccessory)
    char = acc.get_service("Switch").get_characteristic("On")
    char.client_update_value(True)
    assert received == [True]


def test_make_accessory_unknown_type_returns_none(driver):
    assert make_accessory(driver=driver, hk_type="nonsense", name="x") is None
