"""Smoke tests for the __main__ entrypoint wiring.

``build()`` must assemble all components with injected fakes without binding
any real network ports.  No HAP mDNS, no Uvicorn, no Modbus.
"""

import os
import pathlib
import pytest

from homekit_bridge.__main__ import build, AppComponents
from homekit_bridge.models import HKType


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
    def read_holding_registers(self, addr, count, slave=1):
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
