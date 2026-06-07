import pytest
from homekit_bridge.settings import Settings


def test_reads_required_and_defaults(monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "192.168.1.10")
    monkeypatch.setenv("SOLAREDGE_HOST", "192.168.1.20")
    monkeypatch.delenv("SOLAREDGE_UNIT_ID", raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    monkeypatch.delenv("STATE_DIR", raising=False)

    s = Settings.from_env()
    assert s.ccu3_host == "192.168.1.10"
    assert s.solaredge_host == "192.168.1.20"
    assert s.solaredge_unit_id == 1       # default
    assert s.web_password is None          # default
    assert s.state_dir == "./state"        # default


def test_reads_optional_overrides(monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "host-a")
    monkeypatch.setenv("SOLAREDGE_HOST", "host-b")
    monkeypatch.setenv("SOLAREDGE_UNIT_ID", "3")
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    monkeypatch.setenv("STATE_DIR", "/data/state")

    s = Settings.from_env()
    assert s.solaredge_unit_id == 3
    assert s.web_password == "secret"
    assert s.state_dir == "/data/state"


def test_missing_ccu3_host_raises(monkeypatch):
    monkeypatch.delenv("CCU3_HOST", raising=False)
    monkeypatch.setenv("SOLAREDGE_HOST", "host-b")
    with pytest.raises(ValueError, match="CCU3_HOST"):
        Settings.from_env()


def test_missing_solaredge_host_raises(monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "host-a")
    monkeypatch.delenv("SOLAREDGE_HOST", raising=False)
    with pytest.raises(ValueError, match="SOLAREDGE_HOST"):
        Settings.from_env()


def test_invalid_unit_id_gives_descriptive_error(monkeypatch):
    monkeypatch.setenv("CCU3_HOST", "host-a")
    monkeypatch.setenv("SOLAREDGE_HOST", "host-b")
    monkeypatch.setenv("SOLAREDGE_UNIT_ID", "not-a-number")
    with pytest.raises(ValueError, match="SOLAREDGE_UNIT_ID"):
        Settings.from_env()
