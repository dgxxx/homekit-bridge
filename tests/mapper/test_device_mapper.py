import pytest

from homekit_bridge.mapper.device_mapper import (
    auto_hk_type,
    describe_hm_type,
    pv_accessory_specs,
    resolve_hk_type,
)
from homekit_bridge.models import Channel, HKType, PVData


# ---------------------------------------------------------------------------
# Task 9: auto_hk_type — parametrised mapping table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hm,expected", [
    ("SWITCH", HKType.SWITCH),
    ("SWITCH_INTERFACE", HKType.SWITCH),    # substring match
    ("DIMMER", HKType.LIGHTBULB),
    ("BLIND", HKType.COVER),
    ("SHUTTER_CONTACT", HKType.CONTACT),
    ("ROTARY_HANDLE_TRANSCEIVER", HKType.CONTACT),   # HmIP-SRH window handle
    ("CLIMATECONTROL_RT_TRANSCEIVER", HKType.THERMOSTAT),
    ("CLIMATECONTROL_VENT_DRIVE", HKType.THERMOSTAT),
    ("THERMALCONTROL_TRANSMIT", HKType.THERMOSTAT),
    ("MOTIONDETECTOR", HKType.MOTION),
    ("MOTIONDETECTOR_TRANSCEIVER", HKType.MOTION),
    ("WEATHER", HKType.TEMPERATURE),
    ("WEATHER_TRANSMIT", HKType.TEMPERATURE),
    ("TEMPERATURE", HKType.TEMPERATURE),
    ("HUMIDITY", HKType.HUMIDITY),
    ("SYSVAR_BOOL", HKType.SWITCH),         # boolean CCU3 system variable
    ("UNKNOWN_FOO", None),
    ("", None),
])
def test_auto_hk_type(hm, expected):
    assert auto_hk_type(hm) == expected


def test_auto_hk_type_case_insensitive():
    # HM types come in uppercase from the CCU3; the mapper should still handle
    # lowercase gracefully without crashing.
    assert auto_hk_type("switch") == HKType.SWITCH


# ---------------------------------------------------------------------------
# describe_hm_type — human-readable role hint for the device table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hm,needle", [
    # The shutter family must disambiguate: actuator (steuerbar) vs status vs key.
    ("SHUTTER_VIRTUAL_RECEIVER", "steuerbar"),   # the writable blind actuator
    ("SHUTTER_TRANSMITTER",      "nur lesbar"),  # read-only level/status
    ("KEY_TRANSCEIVER",          "Tastenkanal"),  # button: no state, not the actuator
    ("SHUTTER_CONTACT",          "Kontakt"),      # window/door contact
    ("MAINTENANCE",              "Wartung"),
    ("SWITCH_VIRTUAL_RECEIVER",  "Schalt"),
    ("DIMMER",                   "Dimmer"),
    ("HEATING_CLIMATECONTROL_TRANSCEIVER", "Thermostat"),
    ("MOTIONDETECTOR",           "Bewegung"),
    ("SYSVAR_BOOL",              "Systemvariable"),
])
def test_describe_hm_type_contains_hint(hm, needle):
    assert needle.lower() in describe_hm_type(hm).lower()


def test_describe_hm_type_unknown_is_empty():
    assert describe_hm_type("FOO_BAR_BAZ") == ""
    assert describe_hm_type("") == ""


# ---------------------------------------------------------------------------
# Task 9: resolve_hk_type — config override takes precedence
# ---------------------------------------------------------------------------

def test_resolve_uses_explicit_hk_type():
    ch = Channel(address="A:1", hm_type="SWITCH", name="Lamp", hk_type=HKType.OUTLET)
    mapping = {"hk_type": HKType.OUTLET}
    assert resolve_hk_type(ch, mapping) == HKType.OUTLET


def test_resolve_falls_back_to_auto_when_mapping_none():
    ch = Channel(address="A:1", hm_type="DIMMER", name="Dimmer")
    assert resolve_hk_type(ch, {"hk_type": None}) == HKType.LIGHTBULB


def test_resolve_falls_back_when_no_mapping():
    ch = Channel(address="A:1", hm_type="BLIND", name="Blind")
    assert resolve_hk_type(ch, {}) == HKType.COVER


def test_resolve_returns_none_for_unknown_and_no_override():
    ch = Channel(address="A:1", hm_type="UNKNOWN_TYPE", name="?")
    assert resolve_hk_type(ch, {}) is None


# ---------------------------------------------------------------------------
# Task 10: pv_accessory_specs — Variant C, pure function
# ---------------------------------------------------------------------------

def test_pv_specs_returns_four_entries():
    pv = PVData(power_w=2450.0, energy_today_kwh=14.2, battery_pct=78, producing=True)
    specs = pv_accessory_specs(pv)
    assert len(specs) == 4


def test_pv_specs_lux_sensor():
    pv = PVData(power_w=2450.0, energy_today_kwh=0, producing=True)
    specs = pv_accessory_specs(pv)
    lux = next(s for s in specs if s["kind"] == "light_sensor")
    assert lux["lux"] == pytest.approx(2450.0)


def test_pv_specs_eve_power():
    pv = PVData(power_w=2450.0, energy_today_kwh=14.2, producing=True)
    specs = pv_accessory_specs(pv)
    eve = next(s for s in specs if s["kind"] == "eve_power")
    assert eve["watts"] == pytest.approx(2450.0)
    assert eve["kwh"] == pytest.approx(14.2)


def test_pv_specs_battery():
    pv = PVData(power_w=0, energy_today_kwh=0, battery_pct=78, producing=False)
    specs = pv_accessory_specs(pv)
    bat = next(s for s in specs if s["kind"] == "battery")
    assert bat["pct"] == 78


def test_pv_specs_battery_none_when_absent():
    pv = PVData(power_w=0, energy_today_kwh=0, battery_pct=None, producing=False)
    specs = pv_accessory_specs(pv)
    bat = next(s for s in specs if s["kind"] == "battery")
    assert bat["pct"] is None


def test_pv_specs_producing_contact():
    pv = PVData(power_w=2450.0, energy_today_kwh=0, producing=True)
    specs = pv_accessory_specs(pv)
    prod = next(s for s in specs if s["kind"] == "producing")
    assert prod["on"] is True


def test_pv_specs_producing_false():
    pv = PVData(power_w=0, energy_today_kwh=0, producing=False)
    specs = pv_accessory_specs(pv)
    prod = next(s for s in specs if s["kind"] == "producing")
    assert prod["on"] is False


def test_pv_specs_is_pure():
    """Calling pv_accessory_specs twice with the same input yields equal results."""
    pv = PVData(power_w=1000.0, energy_today_kwh=5.0, battery_pct=50, producing=True)
    assert pv_accessory_specs(pv) == pv_accessory_specs(pv)
