"""Pure HM-datapoint ↔ HomeKit-characteristic mapping tables.

No I/O, no HAP imports.  The bridge consults these to route incoming
``ccu3.state`` events onto ``accessory.update_state`` and to wire writable
characteristics back to the correct Homematic datapoint.
"""

from dataclasses import dataclass

from homekit_bridge.models import HKType


@dataclass(frozen=True)
class DP:
    """One datapoint mapping.

    ``kwarg`` is the ``update_state`` argument name (read direction) or the
    HM datapoint name (write direction).  ``scale`` converts between
    Homematic units and HomeKit units: read does ``value * scale``, write does
    ``value / scale`` (e.g. blind LEVEL 0..1 ↔ HomeKit position 0..100).

    ``via`` (write direction only) names an accessory method that converts the
    HomeKit value into the HM value when a plain scale factor is not enough
    (e.g. thermostat mode → setpoint).
    """

    kwarg: str
    scale: float = 1.0
    via: str | None = None


READ_DATAPOINTS: dict[HKType, dict[str, DP]] = {
    HKType.THERMOSTAT: {
        "ACTUAL_TEMPERATURE": DP("current_temp"),
        "SET_POINT_TEMPERATURE": DP("target_temp"),
        "HUMIDITY": DP("humidity"),
        "SET_POINT_MODE": DP("set_point_mode"),
    },
    HKType.SWITCH:      {"STATE": DP("on")},
    HKType.OUTLET:      {"STATE": DP("on")},
    HKType.CONTACT:     {"STATE": DP("contact_detected")},
    HKType.MOTION:      {"MOTION": DP("motion_detected")},
    HKType.TEMPERATURE: {"ACTUAL_TEMPERATURE": DP("temperature")},
    HKType.HUMIDITY:    {"HUMIDITY": DP("humidity")},
    HKType.COVER:       {"LEVEL": DP("position", scale=100.0)},
    HKType.LIGHTBULB:   {"STATE": DP("on"), "LEVEL": DP("brightness", scale=100.0)},
}

WRITE_DATAPOINTS: dict[HKType, dict[str, DP]] = {
    HKType.THERMOSTAT: {
        "target_temp": DP("SET_POINT_TEMPERATURE"),
        # mode: writes_for_mode returns a {datapoint: value} dict, so the kwarg below
        # is unused (the converter chooses SET_POINT_MODE / SET_POINT_TEMPERATURE itself).
        "mode": DP("SET_POINT_TEMPERATURE", via="writes_for_mode"),
    },
    HKType.SWITCH:     {"on": DP("STATE")},
    HKType.OUTLET:     {"on": DP("STATE")},
    HKType.COVER:      {"position": DP("LEVEL", scale=100.0)},
    HKType.LIGHTBULB:  {"on": DP("STATE"), "brightness": DP("LEVEL", scale=100.0)},
}


def read_update(hk_type: HKType, key: str, value: int | float | bool) -> dict | None:
    """Return ``{update_kwarg: value*scale}`` for a HM datapoint, or None if irrelevant."""
    dp = READ_DATAPOINTS.get(hk_type, {}).get(key)
    if dp is None:
        return None
    return {dp.kwarg: value * dp.scale if dp.scale != 1.0 else value}
