import threading
import time

import pytest

from homekit_bridge.events import EventBus
from homekit_bridge.models import PVData
from homekit_bridge.solaredge.adapter import SolarEdgeAdapter
from homekit_bridge.solaredge import registers as R


# ---------------------------------------------------------------------------
# Helpers to build a fake Modbus response
# ---------------------------------------------------------------------------

class FakeRegisters:
    """Mimics pymodbus ReadHoldingRegistersResponse.registers list."""

    def __init__(self, values: list[int]) -> None:
        self.registers = values
        self.isError = lambda: False


class FakeModbus:
    def __init__(self, raise_: bool = False, values: dict[int, list[int]] | None = None) -> None:
        self._raise = raise_
        # Map start_addr -> register word list
        self._values: dict[int, list[int]] = values or {}

    def read_holding_registers(self, address: int, count: int, slave: int = 1):
        if self._raise:
            raise OSError("timeout")
        return FakeRegisters(self._values.get(address, [0] * count))

    def connect(self) -> bool:
        return True

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Build a fake response that produces known decoded values.
#
# SunSpec AC power block (starting at R.AC_POWER, 2 registers):
#   [0] = power value (int16)  [1] = scale factor (int16 as two's-complement)
# Battery SoC (starting at R.BATTERY_SOC, 1 register): raw % (0-100)
# Energy today (starting at R.ENERGY_TODAY, 2 registers):
#   [0] = energy value  [1] = scale factor
# ---------------------------------------------------------------------------

def _make_values(power_w: int = 2500, battery_pct: int = 75, energy_wh: int = 14200) -> dict[int, list[int]]:
    """Return register word map for known SunSpec values.

    Scale factor 0 means multiply by 10^0 = 1, so raw value == decoded value.
    """
    return {
        R.AC_POWER: [power_w, 0],         # value=2500, sf=0  => 2500 W
        R.BATTERY_SOC: [battery_pct],      # 75 %
        R.ENERGY_TODAY: [energy_wh, 0],    # value=14200, sf=0  => 14200 Wh => 14.2 kWh
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_read_decodes_power():
    client = FakeModbus(values=_make_values(power_w=2500))
    adapter = SolarEdgeAdapter(client=client)
    pv = adapter.read()
    assert pv.available
    assert pv.power_w == pytest.approx(2500.0)


def test_read_decodes_battery_pct():
    client = FakeModbus(values=_make_values(battery_pct=75))
    adapter = SolarEdgeAdapter(client=client)
    pv = adapter.read()
    assert pv.battery_pct == 75


def test_read_decodes_energy_today():
    client = FakeModbus(values=_make_values(energy_wh=14200))
    adapter = SolarEdgeAdapter(client=client)
    pv = adapter.read()
    # 14200 Wh = 14.2 kWh
    assert pv.energy_today_kwh == pytest.approx(14.2, rel=1e-3)


def test_producing_true_when_power_above_threshold():
    client = FakeModbus(values=_make_values(power_w=100))
    adapter = SolarEdgeAdapter(client=client, producing_threshold_w=10.0)
    pv = adapter.read()
    assert pv.producing is True


def test_producing_false_when_power_below_threshold():
    client = FakeModbus(values=_make_values(power_w=5))
    adapter = SolarEdgeAdapter(client=client, producing_threshold_w=10.0)
    pv = adapter.read()
    assert pv.producing is False


def test_read_handles_timeout():
    adapter = SolarEdgeAdapter(client=FakeModbus(raise_=True))
    pv = adapter.read()
    assert pv.available is False


def test_read_error_does_not_raise():
    adapter = SolarEdgeAdapter(client=FakeModbus(raise_=True))
    # Must not raise
    result = adapter.read()
    assert isinstance(result, PVData)


def test_sunspec_scale_factor_negative():
    """Scale factor -1 (0xFFFF as int16) means multiply value by 10^-1 = 0.1."""
    # power_raw=25000, sf=-1 => 25000 * 0.1 = 2500.0 W
    values = {
        R.AC_POWER: [25000, 0xFFFF],  # 25000 value, sf=-1 (0xFFFF as int16 = -1)
        R.BATTERY_SOC: [80],
        R.ENERGY_TODAY: [1000, 0],
    }
    client = FakeModbus(values=values)
    adapter = SolarEdgeAdapter(client=client)
    pv = adapter.read()
    assert pv.available
    # 25000 * 10^(-1) = 2500.0
    assert pv.power_w == pytest.approx(2500.0)


def test_poll_publishes_to_bus():
    received: list[PVData] = []
    bus = EventBus()
    bus.subscribe("solaredge.data", lambda e: received.append(e))

    client = FakeModbus(values=_make_values(power_w=1000))
    adapter = SolarEdgeAdapter(client=client)
    stop_event = threading.Event()

    thread = threading.Thread(
        target=adapter.poll,
        kwargs={"bus": bus, "interval": 0.01, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()

    deadline = time.time() + 2.0
    while not received and time.time() < deadline:
        time.sleep(0.01)

    stop_event.set()
    thread.join(timeout=1.0)

    assert len(received) >= 1
    assert isinstance(received[0], PVData)
    assert received[0].available


def test_poll_continues_after_error():
    """A single read error must not terminate the poll loop."""
    call_count = [0]
    received: list[PVData] = []
    bus = EventBus()
    bus.subscribe("solaredge.data", lambda e: received.append(e))
    stop_event = threading.Event()

    class AlternatingModbus:
        def read_holding_registers(self, address, count, slave=1):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("first call fails")
            return FakeRegisters(_make_values(power_w=500).get(address, [0] * count))

        def connect(self):
            return True

        def close(self):
            pass

    adapter = SolarEdgeAdapter(client=AlternatingModbus())

    thread = threading.Thread(
        target=adapter.poll,
        kwargs={"bus": bus, "interval": 0.01, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()

    # Wait for at least one successful publish after the initial error
    deadline = time.time() + 2.0
    while len(received) < 2 and time.time() < deadline:
        time.sleep(0.01)

    stop_event.set()
    thread.join(timeout=1.0)

    # Should have published at least one PVData(available=False) and one successful read
    assert len(received) >= 2
