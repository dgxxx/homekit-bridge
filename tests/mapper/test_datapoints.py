from homekit_bridge.mapper.datapoints import read_update, WRITE_DATAPOINTS
from homekit_bridge.models import HKType


def test_thermostat_read_datapoints():
    assert read_update(HKType.THERMOSTAT, "ACTUAL_TEMPERATURE", 25.0) == {"current_temp": 25.0}
    assert read_update(HKType.THERMOSTAT, "SET_POINT_TEMPERATURE", 4.5) == {"target_temp": 4.5}
    assert read_update(HKType.THERMOSTAT, "HUMIDITY", 40) == {"humidity": 40}


def test_thermostat_reads_set_point_mode():
    assert read_update(HKType.THERMOSTAT, "SET_POINT_MODE", 0) == {"set_point_mode": 0}
    assert read_update(HKType.THERMOSTAT, "SET_POINT_MODE", 1) == {"set_point_mode": 1}


def test_thermostat_ignores_unknown_datapoints():
    assert read_update(HKType.THERMOSTAT, "BOOST_MODE", False) is None
    assert read_update(HKType.THERMOSTAT, "PARTY_MODE", False) is None


def test_switch_read():
    assert read_update(HKType.SWITCH, "STATE", True) == {"on": True}


def test_contact_read_inverts_hm_state():
    # Homematic STATE: 0 = CLOSED, 1 = OPEN (door/window contact).  HomeKit's
    # ContactSensorAccessory expects ``contact_detected`` = True when *closed*,
    # so the raw STATE must be inverted on the way in.
    assert read_update(HKType.CONTACT, "STATE", 0) == {"contact_detected": True}   # closed
    assert read_update(HKType.CONTACT, "STATE", 1) == {"contact_detected": False}  # open


def test_contact_read_rotary_handle_tilted_counts_as_open():
    # HmIP-SRH rotary handle STATE: 0 = CLOSED, 1 = TILTED, 2 = OPEN.  Anything
    # other than fully closed must report "not detected" (open) to HomeKit.
    assert read_update(HKType.CONTACT, "STATE", 2) == {"contact_detected": False}  # open
    assert read_update(HKType.CONTACT, "STATE", 1) == {"contact_detected": False}  # tilted


def test_window_read_maps_state_to_open():
    # WINDOW/DOOR expose the same HM contact channel as a position-based tile.
    # HM STATE: 0 = CLOSED, 1 = OPEN -> open = bool(STATE), no inversion.
    assert read_update(HKType.WINDOW, "STATE", 1) == {"open": True}   # open
    assert read_update(HKType.WINDOW, "STATE", 0) == {"open": False}  # closed


def test_door_read_maps_state_to_open():
    assert read_update(HKType.DOOR, "STATE", 1) == {"open": True}
    assert read_update(HKType.DOOR, "STATE", 0) == {"open": False}


def test_window_and_door_are_read_only():
    assert HKType.WINDOW not in WRITE_DATAPOINTS
    assert HKType.DOOR not in WRITE_DATAPOINTS


def test_cover_level_is_scaled_to_percent():
    assert read_update(HKType.COVER, "LEVEL", 0.5) == {"position": 50.0}


def test_unknown_type_returns_none():
    assert read_update(HKType.MOTION, "NONSENSE", 1) is None


def test_write_datapoints_table():
    assert WRITE_DATAPOINTS[HKType.THERMOSTAT]["target_temp"].kwarg == "SET_POINT_TEMPERATURE"
    assert WRITE_DATAPOINTS[HKType.SWITCH]["on"].kwarg == "STATE"


def test_thermostat_mode_write_uses_writes_for_mode():
    assert WRITE_DATAPOINTS[HKType.THERMOSTAT]["mode"].via == "writes_for_mode"
