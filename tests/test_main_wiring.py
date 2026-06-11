"""Smoke tests for the __main__ entrypoint wiring.

``build()`` must assemble all components with injected fakes without binding
any real network ports.  No HAP mDNS, no Uvicorn, no real MQTT.
"""

import logging

from homekit_bridge.__main__ import build, AppComponents
from homekit_bridge.mqttsource import MqttSource


# ---------------------------------------------------------------------------
# Fake injected to avoid real network / hardware
# ---------------------------------------------------------------------------

class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None

    def connect_async(self, *a, **k):
        pass

    def loop_start(self):
        pass

    def subscribe(self, *a, **k):
        pass

    def publish(self, *a, **k):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_returns_app_components(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    assert isinstance(components, AppComponents)
    assert components.app is not None      # FastAPI app
    assert components.config_store is not None
    assert components.bus is not None
    assert components.settings is not None


def test_build_creates_state_dir_if_missing(tmp_path, monkeypatch):
    state_dir = tmp_path / "missing_subdir" / "state"
    monkeypatch.setenv("STATE_DIR", str(state_dir))

    build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    assert state_dir.exists()


def test_build_uses_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "192.168.1.235")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    assert components.settings.mqtt_host == "192.168.1.235"
    assert components.settings.mqtt_port == 1884


def test_build_ccu3_adapter_is_mqtt_source(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    assert isinstance(components.ccu3_adapter, MqttSource)


def test_build_hap_bridge_built(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
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
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    # driver.accessory must be set — that's what driver.start() serves
    driver = components.hap_driver
    assert driver.accessory is not None, "HAP driver has no accessory — bridge not registered"


def test_bridge_state_paired_reflects_hap_driver(tmp_path, monkeypatch):
    """/api/status's paired flag must track the HAP driver, not a stale False.

    Regression: bridge_state.paired was hard-coded False and never updated, so
    the UI showed "Nicht gepairt" even after pairing in the Home app.
    """
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(
        fakes={
            "mqtt_client": FakeMqttClient(),
        }
    )

    bridge_state = components.bridge_state
    assert bridge_state.paired is False  # freshly built driver has no clients

    # Simulate a successful pairing in the Home app.
    components.hap_driver.state.add_paired_client(
        b"12345678-1234-1234-1234-123456789abc", b"\x00" * 32, b"\x01"
    )
    assert bridge_state.paired is True


def test_create_app_receives_bus(tmp_path, monkeypatch):
    """build() must pass the EventBus into create_app so POSTs can publish."""
    import homekit_bridge.__main__ as m
    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(m, "create_app", fake_create_app)
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    m.build(fakes={"mqtt_client": FakeMqttClient()})

    assert "bus" in captured
    assert captured["bus"] is not None


def test_build_exposes_log_buffer(tmp_path, monkeypatch):
    """build() installs a RingBufferLogHandler and exposes it on AppComponents."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(fakes={"mqtt_client": FakeMqttClient()})

    from homekit_bridge.logbuffer import RingBufferLogHandler
    assert isinstance(components.log_buffer, RingBufferLogHandler)
    # The handler is attached to the root logger so it captures all output.
    assert components.log_buffer in logging.getLogger().handlers


def test_build_passes_fixed_pin_and_mac_to_driver(tmp_path, monkeypatch):
    """A configured HOMEKIT_PIN/HOMEKIT_MAC must reach the AccessoryDriver.

    pyhap does not persist the pincode, so without this the setup code is
    randomly regenerated on every restart. Passing a fixed pincode (bytes) and
    mac keeps the setup code stable and preserves the bridge identity even if
    hap.state is lost.
    """
    import homekit_bridge.__main__ as m

    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HOMEKIT_PIN", "843-19-572")
    monkeypatch.setenv("HOMEKIT_MAC", "11:6D:AA:50:70:CA")

    captured = {}
    real_driver = m.AccessoryDriver

    def capturing_driver(*args, **kwargs):
        captured.update(kwargs)
        return real_driver(*args, **kwargs)

    monkeypatch.setattr(m, "AccessoryDriver", capturing_driver)
    m.build(fakes={"mqtt_client": FakeMqttClient()})

    assert captured["pincode"] == b"843-19-572"
    assert captured["mac"] == "11:6D:AA:50:70:CA"


def test_build_driver_pin_mac_default_none(tmp_path, monkeypatch):
    """Without the env vars, pincode/mac default to None (pyhap generates them)."""
    import homekit_bridge.__main__ as m

    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.delenv("HOMEKIT_PIN", raising=False)
    monkeypatch.delenv("HOMEKIT_MAC", raising=False)

    captured = {}
    real_driver = m.AccessoryDriver

    def capturing_driver(*args, **kwargs):
        captured.update(kwargs)
        return real_driver(*args, **kwargs)

    monkeypatch.setattr(m, "AccessoryDriver", capturing_driver)
    m.build(fakes={"mqtt_client": FakeMqttClient()})

    assert captured["pincode"] is None
    assert captured["mac"] is None


def test_bridge_state_pairing_accessors(tmp_path, monkeypatch):
    """_BridgeState exposes the real PIN and xhm:// pairing URI from the driver."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(fakes={"mqtt_client": FakeMqttClient()})

    bs = components.bridge_state
    assert isinstance(bs.pairing_pin(), str)
    assert bs.pairing_uri().startswith("X-HM://")
