"""HAP accessory factory classes for homekit-bridge.

Each class wraps a pyhap Accessory, wires a HomeKit service, and exposes:
- ``on_get`` callback (optional, for read-on-demand)
- ``update_state(...)`` method to push values from event-bus events
- ``writable_characteristics()`` mapping, wired by the bridge for SET commands

PV accessories (LightSensor, EvePower, Battery, Producing) mirror the four
spec kinds returned by ``pv_accessory_specs``.
"""

import logging
from typing import Callable, Optional

from pyhap.accessory import Accessory
from pyhap.accessory_driver import AccessoryDriver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CCU3 accessories
# ---------------------------------------------------------------------------

class SwitchAccessory(Accessory):
    """On/Off switch."""

    category = 8  # HAP category: Switch

    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
        on_get: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Switch")
        self._char_on = svc.get_characteristic("On")
        if on_get:
            self._char_on.getter_callback = on_get

    def update_state(self, on: bool) -> None:
        self._char_on.set_value(on)

    def writable_characteristics(self) -> dict:
        return {"on": self._char_on}


class OutletAccessory(Accessory):
    """Outlet (smart plug)."""

    category = 7  # HAP category: Outlet

    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
        on_get: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Outlet")
        self._char_on = svc.get_characteristic("On")
        self._char_in_use = svc.get_characteristic("OutletInUse")
        self._char_in_use.set_value(True)  # default: outlet is in use
        if on_get:
            self._char_on.getter_callback = on_get

    def update_state(self, on: bool) -> None:
        self._char_on.set_value(on)

    def writable_characteristics(self) -> dict:
        return {"on": self._char_on}


class LightbulbAccessory(Accessory):
    """Dimmable lightbulb (On + Brightness)."""

    category = 5  # HAP category: Lightbulb

    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Lightbulb", chars=["On", "Brightness"])
        self._char_on = svc.get_characteristic("On")
        self._char_brightness = svc.get_characteristic("Brightness")

    def update_state(self, on: Optional[bool] = None, brightness: Optional[int] = None) -> None:
        if on is not None:
            self._char_on.set_value(on)
        if brightness is not None:
            self._char_brightness.set_value(brightness)

    def writable_characteristics(self) -> dict:
        return {"on": self._char_on, "brightness": self._char_brightness}


class CoverAccessory(Accessory):
    """Window covering (blind / shutter)."""

    category = 14  # HAP category: Window Covering

    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("WindowCovering")
        self._char_current = svc.get_characteristic("CurrentPosition")
        self._char_target = svc.get_characteristic("TargetPosition")
        self._char_state = svc.get_characteristic("PositionState")
        self._char_state.set_value(2)  # 2 = stopped

    def update_state(
        self,
        current_position: Optional[int] = None,
        target_position: Optional[int] = None,
        position: Optional[int] = None,
    ) -> None:
        if position is not None:
            self._char_current.set_value(position)
            self._char_target.set_value(position)
        if current_position is not None:
            self._char_current.set_value(current_position)
        if target_position is not None:
            self._char_target.set_value(target_position)

    def writable_characteristics(self) -> dict:
        return {"position": self._char_target}


class ThermostatAccessory(Accessory):
    """Thermostat (current + target temperature, heat/off mode).

    HmIP signals "off" via the frost-protection setpoint (4.5 °C).  HomeKit's
    TargetTemperature minimum is 10 °C, so setpoints below ``_OFF_THRESHOLD``
    map to mode "off" while the last heating setpoint stays displayed.
    """

    category = 9  # HAP category: Thermostat

    OFF_SETPOINT = 4.5    # HmIP frost protection == "off"
    _OFF_THRESHOLD = 10.0  # below HomeKit's displayable minimum → "off"

    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Thermostat", chars=["CurrentRelativeHumidity"])
        self._char_current = svc.get_characteristic("CurrentTemperature")
        self._char_target = svc.get_characteristic("TargetTemperature")
        self._char_humidity = svc.get_characteristic("CurrentRelativeHumidity")
        self._char_hc_current = svc.get_characteristic("CurrentHeatingCoolingState")
        self._char_hc_target = svc.get_characteristic("TargetHeatingCoolingState")
        self._char_units = svc.get_characteristic("TemperatureDisplayUnits")
        # HmIP heating setpoint range, clamped to Apple's spec minimum of 10 °C
        self._char_target.override_properties(
            properties={"minValue": 10.0, "maxValue": 30.5, "minStep": 0.5}
        )
        # Heating device with HmIP schedule: Off / Heat / Auto (no cooling)
        self._char_hc_target.override_properties(
            valid_values={"Off": 0, "Heat": 1, "Auto": 3}
        )
        self._char_hc_current.set_value(1)
        self._char_hc_target.set_value(1)
        # HmIP SET_POINT_MODE: 0 = AUTO (weekly profile), 1 = MANU. Last raw setpoint
        # (may be the 4.5 °C frost value) is remembered to derive Off vs Heat.
        self._set_point_mode = 1
        self._raw_setpoint: Optional[float] = None

    def update_state(
        self,
        current_temp: Optional[float] = None,
        target_temp: Optional[float] = None,
        humidity: Optional[float] = None,
        set_point_mode: Optional[int] = None,
    ) -> None:
        if current_temp is not None:
            self._char_current.set_value(current_temp)
        if humidity is not None:
            self._char_humidity.set_value(humidity)
        if target_temp is not None:
            self._raw_setpoint = target_temp
            if target_temp >= self._OFF_THRESHOLD:
                # Keep the last real heating setpoint for display + Heat restore;
                # frost/eco values below 10 °C never overwrite it.
                self._char_target.set_value(target_temp)
        if set_point_mode is not None:
            self._set_point_mode = set_point_mode
        if target_temp is not None or set_point_mode is not None:
            self._apply_mode()

    def _apply_mode(self) -> None:
        """Derive HomeKit heat/cool state from SET_POINT_MODE + last setpoint."""
        if self._set_point_mode == 0:           # HmIP AUTO → HomeKit Auto
            self._char_hc_target.set_value(3)
            # CurrentHeatingCoolingState has no "Auto"; we show Heat. (Even if the
            # scheduled setpoint is momentarily frost, Current stays Heat — acceptable.)
            self._char_hc_current.set_value(1)
            return
        # MANU: frost setpoint == off, otherwise heating
        if self._raw_setpoint is not None and self._raw_setpoint < self._OFF_THRESHOLD:
            self._char_hc_current.set_value(0)
            self._char_hc_target.set_value(0)
        else:
            self._char_hc_current.set_value(1)
            self._char_hc_target.set_value(1)

    def writes_for_mode(self, mode: int) -> dict[str, int | float]:
        """HM datapoints realizing a HomeKit mode write.

        The HmIP control mode is set via ``CONTROL_MODE`` (0 = AUTO/weekly profile,
        1 = MANU).  ``SET_POINT_MODE`` is read-only in practice — the CCU rejects
        ``setValue`` on it — so it is consumed only on the read path, never written.

        Off (0)  → CONTROL_MODE 1 (MANU) + frost setpoint (4.5 °C turns heating off).
        Auto (3) → CONTROL_MODE 0 (follow the HmIP weekly profile).
        Heat (1) → CONTROL_MODE 1 (MANU) + restore the last heating setpoint still
                   held by TargetTemperature (never overwritten by "off").  On a
                   fresh accessory (no setpoint received yet) this is
                   TargetTemperature's initial value (the HAP minimum).
        """
        if mode == 0:
            # Force MANU so "off" sticks even if the device was in AUTO; the frost
            # setpoint (4.5 °C) is what actually turns the heating off.
            return {"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": self.OFF_SETPOINT}
        if mode == 3:
            return {"CONTROL_MODE": 0}
        return {"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": float(self._char_target.value)}

    def writable_characteristics(self) -> dict:
        return {"target_temp": self._char_target, "mode": self._char_hc_target}


class ContactSensorAccessory(Accessory):
    """Contact sensor (door/window)."""

    category = 21  # HAP category: Sensor

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("ContactSensor")
        self._char_state = svc.get_characteristic("ContactSensorState")

    def update_state(self, contact_detected: bool) -> None:
        # ContactSensorState: 0 = contact detected (closed), 1 = not detected (open)
        self._char_state.set_value(0 if contact_detected else 1)


class TemperatureSensorAccessory(Accessory):
    """Temperature sensor (read-only)."""

    category = 21

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("TemperatureSensor")
        self._char_temp = svc.get_characteristic("CurrentTemperature")

    def update_state(self, temperature: float) -> None:
        self._char_temp.set_value(temperature)


class HumiditySensorAccessory(Accessory):
    """Relative humidity sensor (read-only)."""

    category = 21

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("HumiditySensor")
        self._char_humidity = svc.get_characteristic("CurrentRelativeHumidity")

    def update_state(self, humidity: float) -> None:
        self._char_humidity.set_value(humidity)


class MotionSensorAccessory(Accessory):
    """Motion sensor (read-only)."""

    category = 21

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("MotionSensor")
        self._char_motion = svc.get_characteristic("MotionDetected")

    def update_state(self, motion_detected: bool) -> None:
        self._char_motion.set_value(motion_detected)


# ---------------------------------------------------------------------------
# PV accessories
# ---------------------------------------------------------------------------

class LightSensorAccessory(Accessory):
    """LightSensor used as a proxy for PV AC power (lux == watts)."""

    category = 21

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("LightSensor")
        self._char_lux = svc.get_characteristic("CurrentAmbientLightLevel")

    def update_state(self, lux: float) -> None:
        # HAP LightSensor min is 0.0001; clamp to avoid HAP validation errors
        self._char_lux.set_value(max(0.0001, lux))


class EvePowerAccessory(Accessory):
    """Eve Energy-style custom accessory exposing watts and kWh.

    Eve uses custom Bluetooth-based UUIDs; we store values internally and
    expose them via a read-only custom service.  The stored values are
    accessible as ``current_watts`` and ``current_kwh`` for testing.
    """

    category = 7  # Outlet category for compatibility

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        # Expose a plain Switch service so HAP doesn't reject the accessory;
        # actual power values are stored as Python attributes.
        svc = self.add_preload_service("Switch")
        self._char_on = svc.get_characteristic("On")
        self._char_on.set_value(True)
        self.current_watts: float = 0.0
        self.current_kwh: float = 0.0

    def update_state(self, watts: float, kwh: float) -> None:
        self.current_watts = watts
        self.current_kwh = kwh
        # Reflect producing state on the On characteristic
        self._char_on.set_value(watts > 0)


class BatteryAccessory(Accessory):
    """Battery state-of-charge accessory."""

    category = 21

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("BatteryService")
        self._char_level = svc.get_characteristic("BatteryLevel")
        self._char_charging = svc.get_characteristic("ChargingState")
        self._char_low = svc.get_characteristic("StatusLowBattery")
        # Solar battery: typically charging or not charging (never 2=not chargeable)
        self._char_charging.set_value(0)

    def update_state(self, pct: Optional[int]) -> None:
        if pct is None:
            return  # battery absent — leave at default
        self._char_level.set_value(pct)
        self._char_low.set_value(1 if pct < 20 else 0)


class ProducingAccessory(Accessory):
    """Read-only Switch accessory indicating whether the inverter is producing."""

    category = 8  # Switch

    def __init__(self, driver: AccessoryDriver, name: str) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Switch")
        self._char_on = svc.get_characteristic("On")

    def update_state(self, on: bool) -> None:
        self._char_on.set_value(on)


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

_FACTORY_MAP: dict[str, type] = {
    "switch": SwitchAccessory,
    "outlet": OutletAccessory,
    "lightbulb": LightbulbAccessory,
    "cover": CoverAccessory,
    "thermostat": ThermostatAccessory,
    "contact": ContactSensorAccessory,
    "temperature": TemperatureSensorAccessory,
    "humidity": HumiditySensorAccessory,
    "motion": MotionSensorAccessory,
}


def make_accessory(
    driver: AccessoryDriver,
    hk_type: str,
    name: str,
) -> Optional[Accessory]:
    """Instantiate the correct accessory class for *hk_type*.

    Returns ``None`` for unknown types so callers can skip gracefully.  Writable
    characteristics are wired by the bridge via ``writable_characteristics()``.
    """
    cls = _FACTORY_MAP.get(hk_type)
    if cls is None:
        logger.warning("Unknown HKType '%s' for accessory '%s'", hk_type, name)
        return None
    return cls(driver=driver, name=name)
