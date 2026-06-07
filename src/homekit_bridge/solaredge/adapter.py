"""SolarEdge Modbus TCP adapter.

Reads AC power, battery SoC and today's energy from the inverter via
SunSpec Modbus.  All I/O is isolated behind an injected ``client`` so that
tests can run without a real inverter.
"""

import ctypes
import logging
import threading
from typing import Any, Optional

from homekit_bridge.events import EventBus
from homekit_bridge.models import PVData
from homekit_bridge.solaredge import registers as R

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 1502
_DEFAULT_PRODUCING_THRESHOLD_W = 10.0


def _int16(raw: int) -> int:
    """Interpret a uint16 register word as a signed int16."""
    return ctypes.c_int16(raw).value


def _apply_sf(value: int, sf_raw: int) -> float:
    """Apply SunSpec scale factor: result = value * 10^sf."""
    sf = _int16(sf_raw)
    return float(value) * (10.0 ** sf)


class SolarEdgeAdapter:
    """Reads PV data from a SolarEdge inverter over Modbus TCP.

    Pass a ``client`` in tests to avoid real network calls.  The client must
    expose ``read_holding_registers(address, count, slave=int)``.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = _DEFAULT_PORT,
        unit_id: int = 1,
        client: Any = None,
        producing_threshold_w: float = _DEFAULT_PRODUCING_THRESHOLD_W,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            # Import here so tests without pymodbus installed still work
            from pymodbus.client import ModbusTcpClient  # type: ignore
            self._client = ModbusTcpClient(host, port=port)

        self._unit_id = unit_id
        self._producing_threshold_w = producing_threshold_w

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def read(self) -> PVData:
        """Read a single snapshot from the inverter.

        Returns ``PVData(available=False)`` on any I/O or decode error —
        never raises.
        """
        try:
            return self._read_registers()
        except Exception:
            logger.exception("SolarEdge read failed")
            return PVData(available=False)

    def poll(
        self,
        bus: EventBus,
        interval: float = 5.0,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """Blocking poll loop — run in a background thread.

        Publishes each ``PVData`` snapshot (including unavailable ones) to
        ``bus`` on topic ``"solaredge.data"``.  Stops when ``stop_event`` is
        set or the thread is interrupted.
        """
        if stop_event is None:
            stop_event = threading.Event()

        while not stop_event.is_set():
            pv = self.read()
            bus.publish("solaredge.data", pv)
            stop_event.wait(interval)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_registers(self) -> PVData:
        power_w = self._read_ac_power()
        battery_pct = self._read_battery_soc()
        energy_today_kwh = self._read_energy_today()
        producing = power_w > self._producing_threshold_w

        return PVData(
            power_w=power_w,
            energy_today_kwh=energy_today_kwh,
            battery_pct=battery_pct,
            producing=producing,
            available=True,
        )

    def _read_ac_power(self) -> float:
        resp = self._client.read_holding_registers(R.AC_POWER, 2, slave=self._unit_id)
        regs = resp.registers
        return _apply_sf(regs[0], regs[1])

    def _read_battery_soc(self) -> Optional[int]:
        try:
            resp = self._client.read_holding_registers(R.BATTERY_SOC, 1, slave=self._unit_id)
            return int(resp.registers[0])
        except Exception:
            # Battery may not be present — treat as absent rather than failing
            logger.debug("Battery SoC register unavailable")
            return None

    def _read_energy_today(self) -> float:
        try:
            resp = self._client.read_holding_registers(R.ENERGY_TODAY, 2, slave=self._unit_id)
            regs = resp.registers
            wh = _apply_sf(regs[0], regs[1])
            return wh / 1000.0  # Wh -> kWh
        except Exception:
            logger.debug("Energy today register unavailable")
            return 0.0
