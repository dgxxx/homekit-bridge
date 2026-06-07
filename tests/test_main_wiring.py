"""Smoke tests for the __main__ entrypoint wiring.

``build()`` must assemble all components with injected fakes without binding
any real network ports.  No HAP mDNS, no Uvicorn, no real MQTT.
"""

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
