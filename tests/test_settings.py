from homekit_bridge.settings import Settings


def test_defaults(monkeypatch):
    for v in ("MQTT_HOST", "MQTT_PORT", "WEB_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    s = Settings.from_env()
    assert s.mqtt_host == "127.0.0.1"
    assert s.mqtt_port == 1883
    assert s.web_password is None
    assert s.state_dir == "./state"


def test_overrides(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "192.168.1.235")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    monkeypatch.setenv("STATE_DIR", "/data")
    s = Settings.from_env()
    assert s.mqtt_host == "192.168.1.235"
    assert s.mqtt_port == 1884
    assert s.web_password == "secret"
    assert s.state_dir == "/data"
