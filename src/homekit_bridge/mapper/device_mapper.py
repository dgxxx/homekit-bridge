"""Pure device-mapping functions — no I/O, no HAP imports.

``auto_hk_type`` translates raw Homematic channel-type strings to the
nearest HomeKit accessory type using a substring/prefix rule table.

``resolve_hk_type`` applies the explicit override from the config store
first, then falls back to ``auto_hk_type``.

``pv_accessory_specs`` (Variant C) builds a list of accessory-spec dicts
from a ``PVData`` snapshot.  The list is consumed by the HAP bridge to
instantiate real HAP accessories.
"""

from typing import Any, Optional

from homekit_bridge.models import Channel, HKType, PVData


# ---------------------------------------------------------------------------
# Mapping table: ordered list of (substring, HKType) tuples.
# The first match wins; comparison is case-insensitive.
# ---------------------------------------------------------------------------

_HM_RULES: list[tuple[str, HKType]] = [
    # Contact sensors — must come before SHUTTER to catch SHUTTER_CONTACT
    ("CONTACT",      HKType.CONTACT),

    # Covers / blinds
    ("BLIND",        HKType.COVER),
    ("SHUTTER",      HKType.COVER),

    # Thermostats / climate control — longest substrings first
    ("CLIMATECONTROL",    HKType.THERMOSTAT),
    ("THERMALCONTROL",    HKType.THERMOSTAT),
    ("THERMOSTAT",        HKType.THERMOSTAT),

    # Motion detectors
    ("MOTIONDETECTOR", HKType.MOTION),
    ("MOTION",         HKType.MOTION),

    # Light dimmers
    ("DIMMER",       HKType.LIGHTBULB),

    # Humidity before temperature (HUMIDITY is more specific)
    ("HUMIDITY",     HKType.HUMIDITY),

    # Temperature / weather sensors
    ("TEMPERATURE",  HKType.TEMPERATURE),
    ("WEATHER",      HKType.TEMPERATURE),

    # Generic switches / outlets
    ("SWITCH",       HKType.SWITCH),
    ("OUTLET",       HKType.OUTLET),
]


def auto_hk_type(hm_type: str) -> Optional[HKType]:
    """Return the best HomeKit type for a raw Homematic channel-type string.

    Returns ``None`` when no rule matches (unknown types should be ignored
    by the bridge rather than exposed with a wrong accessory type).
    """
    upper = hm_type.upper()
    for substring, hk in _HM_RULES:
        if substring in upper:
            return hk
    return None


def resolve_hk_type(
    channel: Channel,
    mapping: dict[str, Any],
) -> Optional[HKType]:
    """Resolve the effective HomeKit type for a channel.

    Priority:
    1. Explicit override stored in *mapping* (from the config store).
    2. Automatic detection via ``auto_hk_type`` using the channel's raw type.
    """
    override: Optional[HKType] = mapping.get("hk_type")
    if override is not None:
        return override
    return auto_hk_type(channel.type)


# ---------------------------------------------------------------------------
# PV accessory specs — Variant C
# ---------------------------------------------------------------------------

def pv_accessory_specs(pv: PVData) -> list[dict[str, Any]]:
    """Return a list of four accessory-spec dicts for a PV data snapshot.

    Variant C representation:
    - ``light_sensor``  — lux value == AC power in watts (visual proxy for irradiance)
    - ``eve_power``     — Eve Energy-style custom accessory (watts + kWh)
    - ``battery``       — battery state-of-charge (pct may be None when no battery)
    - ``producing``     — contact/switch indicating whether the inverter is producing

    These are pure dicts; the HAP bridge layer turns them into real accessories.
    """
    return [
        {
            "kind": "light_sensor",
            "lux": pv.power_w,
        },
        {
            "kind": "eve_power",
            "watts": pv.power_w,
            "kwh": pv.energy_today_kwh,
        },
        {
            "kind": "battery",
            "pct": pv.battery_pct,
        },
        {
            "kind": "producing",
            "on": pv.producing,
        },
    ]
