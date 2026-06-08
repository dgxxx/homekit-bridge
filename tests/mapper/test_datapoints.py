from homekit_bridge.mapper.datapoints import read_update, WRITE_DATAPOINTS
from homekit_bridge.models import HKType


def test_thermostat_read_datapoints():
    assert read_update(HKType.THERMOSTAT, "ACTUAL_TEMPERATURE", 25.0) == {"current_temp": 25.0}
    assert read_update(HKType.THERMOSTAT, "SET_POINT_TEMPERATURE", 4.5) == {"target_temp": 4.5}
    assert read_update(HKType.THERMOSTAT, "HUMIDITY", 40) == {"humidity": 40}


def test_thermostat_ignores_unknown_datapoints():
    assert read_update(HKType.THERMOSTAT, "BOOST_MODE", False) is None
    assert read_update(HKType.THERMOSTAT, "PARTY_MODE", False) is None


def test_switch_and_contact_read():
    assert read_update(HKType.SWITCH, "STATE", True) == {"on": True}
    assert read_update(HKType.CONTACT, "STATE", False) == {"contact_detected": False}


def test_cover_level_is_scaled_to_percent():
    assert read_update(HKType.COVER, "LEVEL", 0.5) == {"position": 50.0}


def test_unknown_type_returns_none():
    assert read_update(HKType.MOTION, "NONSENSE", 1) is None


def test_write_datapoints_table():
    assert WRITE_DATAPOINTS[HKType.THERMOSTAT]["target_temp"].kwarg == "SET_POINT_TEMPERATURE"
    assert WRITE_DATAPOINTS[HKType.SWITCH]["on"].kwarg == "STATE"
