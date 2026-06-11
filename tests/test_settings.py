import pytest

from homekit_bridge.settings import Settings


def test_defaults(monkeypatch):
    for v in ("MQTT_HOST", "MQTT_PORT", "WEB_PASSWORD", "HOMEKIT_PIN", "HOMEKIT_MAC"):
        monkeypatch.delenv(v, raising=False)
    s = Settings.from_env()
    assert s.mqtt_host == "127.0.0.1"
    assert s.mqtt_port == 1883
    assert s.web_password is None
    assert s.state_dir == "./state"
    # No fixed pairing identity by default — pyhap generates a random PIN/MAC.
    assert s.homekit_pin is None
    assert s.homekit_mac is None


def test_overrides(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "192.168.1.235")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    monkeypatch.setenv("STATE_DIR", "/data")
    monkeypatch.setenv("HOMEKIT_PIN", "843-19-572")
    monkeypatch.setenv("HOMEKIT_MAC", "11:6D:AA:50:70:CA")
    s = Settings.from_env()
    assert s.mqtt_host == "192.168.1.235"
    assert s.mqtt_port == 1884
    assert s.web_password == "secret"
    assert s.state_dir == "/data"
    assert s.homekit_pin == "843-19-572"
    assert s.homekit_mac == "11:6D:AA:50:70:CA"


def test_empty_homekit_vars_are_none(monkeypatch):
    """Blank env vars (e.g. `HOMEKIT_PIN=` in .env) mean "not set", not ""."""
    monkeypatch.setenv("HOMEKIT_PIN", "")
    monkeypatch.setenv("HOMEKIT_MAC", "")
    s = Settings.from_env()
    assert s.homekit_pin is None
    assert s.homekit_mac is None


def test_invalid_homekit_pin_raises(monkeypatch):
    """A malformed PIN silently breaks pairing — reject it loudly at startup."""
    monkeypatch.setenv("HOMEKIT_PIN", "12345678")
    with pytest.raises(ValueError, match="HOMEKIT_PIN"):
        Settings.from_env()
