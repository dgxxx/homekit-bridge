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

    # Boolean CCU3 system variables — default to a toggleable Switch
    ("SYSVAR",       HKType.SWITCH),

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


# ---------------------------------------------------------------------------
# Human-readable role hints for the device table.
#
# Derived purely from the raw Homematic channel-type string — the same source
# auto_hk_type uses.  Goal: make it obvious *which* channel of a multi-channel
# device is the controllable one (e.g. a HmIP-BROLL's :4 actuator vs its :1
# button channel), so the right channel gets exported.  Ordered list, first
# substring match wins, case-insensitive.
# ---------------------------------------------------------------------------

_HM_DESCRIPTIONS: list[tuple[str, str]] = [
    # Shutter family — disambiguate actuator vs status vs contact before SHUTTER.
    ("SHUTTER_CONTACT",          "Tür-/Fensterkontakt – offen/geschlossen (nur lesbar)"),
    ("SHUTTER_VIRTUAL_RECEIVER", "Rollladen-/Jalousie-Aktor – Position lesen + fahren (steuerbar)"),
    ("SHUTTER_TRANSMITTER",      "Rollladen-Position – Statuskanal (nur lesbar)"),
    ("BLIND",                    "Rollladen-/Jalousie-Aktor – Position lesen + fahren (steuerbar)"),
    ("SHUTTER",                  "Rollladen-/Jalousie – Position (steuerbar)"),

    # Buttons: send key presses, expose no state and no position.
    ("KEY",                      "Tastenkanal – sendet nur Tastendrücke (kein Status, keine Position)"),

    # Maintenance / device-wide operating data.
    ("MAINTENANCE",              "Wartungskanal – Betriebsdaten (Batterie, Funkqualität)"),

    # Climate.
    ("CLIMATECONTROL",           "Thermostat – Soll-/Ist-Temperatur und Modus (steuerbar)"),
    ("THERMALCONTROL",           "Thermostat – Soll-/Ist-Temperatur und Modus (steuerbar)"),
    ("THERMOSTAT",               "Thermostat – Soll-/Ist-Temperatur und Modus (steuerbar)"),

    ("MOTION",                   "Bewegungsmelder – erkennt Bewegung (nur lesbar)"),
    ("DIMMER",                   "Dimmer – Helligkeit lesen + setzen (steuerbar)"),
    ("SWITCH",                   "Schaltaktor – ein/aus (steuerbar)"),
    ("OUTLET",                   "Schaltbare Steckdose – ein/aus (steuerbar)"),
    ("HUMIDITY",                 "Feuchte-Sensor – relative Luftfeuchte (nur lesbar)"),
    ("WEATHER",                  "Wetter-/Temperatur-Sensor (nur lesbar)"),
    ("TEMPERATURE",              "Temperatur-Sensor (nur lesbar)"),
    ("SYSVAR",                   "CCU-Systemvariable (boolesch) – lesen/schalten"),
    ("CONTACT",                  "Kontakt-Sensor – offen/geschlossen (nur lesbar)"),
]


def describe_hm_type(hm_type: str) -> str:
    """Return a short German role hint for a raw Homematic channel-type string.

    Empty string when the type is unknown — the UI then shows no hint rather
    than a misleading guess.
    """
    upper = hm_type.upper()
    for substring, desc in _HM_DESCRIPTIONS:
        if substring in upper:
            return desc
    return ""


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
    return auto_hk_type(channel.hm_type)


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
