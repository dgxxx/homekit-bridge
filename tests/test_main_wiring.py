"""Smoke tests for the __main__ entrypoint wiring.

``build()`` must assemble all components with injected fakes without binding
any real network ports.  No HAP mDNS, no Uvicorn, no Modbus.
"""

from homekit_bridge.__main__ import build, AppComponents


# ---------------------------------------------------------------------------
# Fakes injected to avoid real network / hardware
# ---------------------------------------------------------------------------

class FakeCcu3Client:
    def init(self, url, iface):
        pass

    def set_value(self, a, k, v):
        pass

    def get_value(self, a, k):
        return None

    def list_devices(self):
        return []


class FakeCallbackServer:
    on_event = None

    @property
    def url(self):
        return "http://127.0.0.1:9999"

    def start(self):
        pass

    def stop(self):
        pass


class FakeModbusClient:
    def read_holding_registers(self, addr, count=1, device_id=1):
        class Resp:
            registers = [0] * count
        return Resp()

    def connect(self):
        return True

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_returns_app_components(tmp_path, monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": FakeModbusClient(),
        }
    )

    assert isinstance(components, AppComponents)
    assert components.app is not None      # FastAPI app
    assert components.config_store is not None
    assert components.bus is not None
    assert components.settings is not None


def test_build_creates_state_dir_if_missing(tmp_path, monkeypatch):
    state_dir = tmp_path / "missing_subdir" / "state"
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.setenv("STATE_DIR", str(state_dir))

    build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": FakeModbusClient(),
        }
    )

    assert state_dir.exists()


def test_build_uses_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "ccu3.local")
    monkeypatch.setenv("SOLAREDGE_HOST", "se.local")
    monkeypatch.setenv("SOLAREDGE_UNIT_ID", "3")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": FakeModbusClient(),
        }
    )

    assert components.settings.ccu3_host == "ccu3.local"
    assert components.settings.solaredge_unit_id == 3


def test_build_hap_bridge_built(tmp_path, monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": FakeModbusClient(),
        }
    )

    from pyhap.accessory import Bridge as HAPBridge
    assert isinstance(components.hap_bridge.hap_bridge, HAPBridge)


def test_hap_driver_has_accessory_registered(tmp_path, monkeypatch):
    """build() must register the bridge with the HAP driver (driver.accessory set).

    Regression: HomeKitBridge.build() previously created the Bridge object but
    never called driver.add_accessory(), so driver.start() would have nothing to
    advertise.
    """
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": FakeModbusClient(),
        }
    )

    # driver.accessory must be set — that's what driver.start() serves
    driver = components.hap_driver
    assert driver.accessory is not None, "HAP driver has no accessory — bridge not registered"


def test_solaredge_adapter_uses_device_id_kwarg(tmp_path, monkeypatch):
    """SolarEdgeAdapter must call read_holding_registers with device_id=, not slave=.

    Regression: pymodbus 3.13 changed the kwarg from slave= to device_id=.
    The fake here uses the real pymodbus 3.x signature to catch future drift.
    """
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    call_kwargs: list[dict] = []

    class StrictModbusClient:
        """Rejects slave= by only accepting device_id= as a keyword arg."""
        def read_holding_registers(self, address: int, *, count: int = 1, device_id: int = 1):
            call_kwargs.append({"address": address, "count": count, "device_id": device_id})
            class Resp:
                registers = [0] * count
            return Resp()

        def connect(self):
            return True

        def close(self):
            pass

    components = build(
        fakes={
            "ccu3_client": FakeCcu3Client(),
            "callback_server": FakeCallbackServer(),
            "modbus_client": StrictModbusClient(),
        }
    )

    # Trigger a single read through the adapter
    components.solaredge_adapter.read()
    assert len(call_kwargs) > 0, "read_holding_registers never called"
    # All calls must have used device_id= (StrictModbusClient would TypeError on slave=)
    assert all("device_id" in kw for kw in call_kwargs)
