"""Tests for the FastAPI web API.

Uses httpx.TestClient with injected fakes for ConfigStore, Ccu3Adapter,
solar state, and Settings.
"""

import base64
import pytest
from httpx import ASGITransport, AsyncClient

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.logbuffer import RingBufferLogHandler
from homekit_bridge.models import Channel, Device, HKType, PVData
from homekit_bridge.settings import Settings
from homekit_bridge.web.api import create_app


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCcu3Adapter:
    def __init__(self, devices=None):
        self._devices = devices or []
        self.set_calls = []

    def list_devices(self):
        return self._devices

    def set_value(self, address, key, value):
        self.set_calls.append((address, key, value))


class FakeSolarState:
    def __init__(self, pv: PVData | None = None):
        self.pv = pv or PVData(power_w=1000.0, energy_today_kwh=5.0, battery_pct=80, producing=True)


class FakeBridgeState:
    def __init__(self):
        self.paired = False
        self.accessory_count = 0
        self.ccu3_connected = True
        self.solaredge_connected = True


class FakeHapBridge:
    def __init__(self):
        self.calls = []
        self.snapshot = [
            {"address": "SW:1", "name": "Lamp", "room": "Bad",
             "hk_type": "switch", "state": {"on": False}},
        ]

    def control_snapshot(self):
        return self.snapshot

    def apply_control(self, address, field, value):
        self.calls.append((address, field, value))
        return address == "SW:1" and field == "on"


# ---------------------------------------------------------------------------
# Settings fixture helpers
# ---------------------------------------------------------------------------

def _make_settings(web_password=None):
    return Settings(
        web_password=web_password,
    )


# ---------------------------------------------------------------------------
# App fixture (no auth)
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "test.db")


@pytest.fixture
def ccu3():
    return FakeCcu3Adapter()


@pytest.fixture
def solar():
    return FakeSolarState()


@pytest.fixture
def bridge_state():
    return FakeBridgeState()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def logbuf():
    return RingBufferLogHandler()


@pytest.fixture
def app(store, ccu3, solar, bridge_state, bus, logbuf):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=bus,
        log_buffer=logbuf,
    )


@pytest.fixture
def auth_app(store, ccu3, solar, bridge_state, bus, logbuf):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(web_password="secret"),
        bus=bus,
        log_buffer=logbuf,
    )


# ---------------------------------------------------------------------------
# Helper: async client context manager
# ---------------------------------------------------------------------------

async def _client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/devices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_devices_empty(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_devices_includes_store_mappings(app, store):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    assert r.status_code == 200
    assert len(data) == 1
    assert data[0]["address"] == "OEQ1:1"
    assert data[0]["exported"] is True
    assert data[0]["hk_type"] == "switch"
    assert data[0]["name"] == "Lamp"


# ---------------------------------------------------------------------------
# POST /api/devices/{address}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_device_persists_to_store(app, store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/devices/OEQ1:1",
            json={"exported": True, "hk_type": "switch", "name": "Lamp"},
        )
    assert r.status_code == 200
    mapping = store.get_mapping("OEQ1:1")
    assert mapping is not None
    assert mapping["exported"] is True
    assert mapping["hk_type"] == HKType.SWITCH
    assert mapping["name"] == "Lamp"


@pytest.mark.asyncio
async def test_post_device_hk_type_null(app, store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/devices/OEQ2:1",
            json={"exported": False, "hk_type": None, "name": "Unknown"},
        )
    assert r.status_code == 200
    mapping = store.get_mapping("OEQ2:1")
    assert mapping["hk_type"] is None


# ---------------------------------------------------------------------------
# GET /api/solar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_solar(app, solar):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/solar")
    assert r.status_code == 200
    data = r.json()
    assert data["power_w"] == pytest.approx(1000.0)
    assert data["energy_today_kwh"] == pytest.approx(5.0)
    assert data["battery_pct"] == 80
    assert data["producing"] is True
    assert data["available"] is True


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status(app, bridge_state):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "paired" in data
    assert "accessory_count" in data
    assert "ccu3_connected" in data
    assert "solaredge_connected" in data


# ---------------------------------------------------------------------------
# Auth: requests without password when WEB_PASSWORD is set → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_required_without_credentials(auth_app):
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_accepted_with_correct_password(auth_app):
    creds = base64.b64encode(b"admin:secret").decode()
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        r = await c.get("/api/devices", headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_rejected_with_wrong_password(auth_app):
    creds = base64.b64encode(b"admin:wrong").decode()
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        r = await c.get("/api/devices", headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_health_unprotected_even_with_password(auth_app):
    """/health should always respond 200, even when auth is enabled."""
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/devices — CCU3 discovery merged with config
# ---------------------------------------------------------------------------

def _make_app_with_ccu3(store, solar, bridge_state, devices):
    adapter = FakeCcu3Adapter(devices=devices)
    return create_app(
        config_store=store,
        ccu3_adapter=adapter,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=EventBus(),
        log_buffer=RingBufferLogHandler(),
    )


@pytest.mark.asyncio
async def test_get_devices_shows_discovered_ccu3_channels(store, solar, bridge_state):
    """Channels discovered from CCU3 appear even without a config-store entry."""
    device = Device(
        address="OEQ1",
        model="HM-LC-Sw1",
        channels=[Channel(address="OEQ1:1", hm_type="SWITCH", name="Channel 1")],
    )
    app = _make_app_with_ccu3(store, solar, bridge_state, [device])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    assert r.status_code == 200
    assert len(data) == 1
    assert data[0]["address"] == "OEQ1:1"
    assert data[0]["type"] == "SWITCH"
    assert data[0]["exported"] is False        # default: not yet exported
    assert data[0]["hk_type"] is None          # no config override yet
    assert data[0]["suggested_hk_type"] == "switch"  # auto-detected


@pytest.mark.asyncio
async def test_get_devices_includes_room_from_discovery(store, solar, bridge_state):
    """The CCU3 room assignment is passed through read-only in /api/devices."""
    device = Device(
        address="OEQ1",
        model="HM-LC-Sw1",
        channels=[Channel(address="OEQ1:1", hm_type="SWITCH", name="Channel 1",
                          room="Wohnzimmer")],
    )
    app = _make_app_with_ccu3(store, solar, bridge_state, [device])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    assert data[0]["room"] == "Wohnzimmer"


@pytest.mark.asyncio
async def test_get_devices_room_empty_when_config_only(store, solar, bridge_state):
    """Config-only channels (not discovered) report an empty room."""
    store.set_mapping("OLD:1", exported=True, hk_type=HKType.SWITCH, name="Old Device")
    app = _make_app_with_ccu3(store, solar, bridge_state, [])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    row = next(d for d in r.json() if d["address"] == "OLD:1")
    assert row["room"] == ""


@pytest.mark.asyncio
async def test_get_devices_config_overrides_discovery(store, solar, bridge_state):
    """Config-store overrides (name, hk_type, exported) take priority over CCU3 defaults."""
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.OUTLET, name="My Outlet")
    device = Device(
        address="OEQ1",
        model="HM-LC-Sw1",
        channels=[Channel(address="OEQ1:1", hm_type="SWITCH", name="Channel 1")],
    )
    app = _make_app_with_ccu3(store, solar, bridge_state, [device])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    assert len(data) == 1
    row = data[0]
    assert row["exported"] is True
    assert row["hk_type"] == "outlet"          # config override wins
    assert row["name"] == "My Outlet"          # config name wins
    assert row["suggested_hk_type"] == "switch"  # auto from raw HM type


@pytest.mark.asyncio
async def test_get_devices_config_only_channels_included(store, solar, bridge_state):
    """Channels in config but not discovered (e.g. CCU3 offline) are still returned."""
    store.set_mapping("OLD:1", exported=True, hk_type=HKType.SWITCH, name="Old Device")
    # CCU3 returns nothing (no devices discovered this session)
    app = _make_app_with_ccu3(store, solar, bridge_state, [])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    assert any(d["address"] == "OLD:1" for d in data)


@pytest.mark.asyncio
async def test_get_devices_ccu3_failure_returns_config_only(store, solar, bridge_state):
    """If list_devices() raises, endpoint falls back to config-store (no crash, 200)."""
    class FailingCcu3:
        def list_devices(self):
            raise ConnectionError("CCU3 offline")

        def set_value(self, a, k, v):
            pass

    store.set_mapping("OEQ2:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    app = create_app(
        config_store=store,
        ccu3_adapter=FailingCcu3(),
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=EventBus(),
        log_buffer=RingBufferLogHandler(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    assert r.status_code == 200
    data = r.json()
    assert any(d["address"] == "OEQ2:1" for d in data)


@pytest.mark.asyncio
async def test_get_devices_no_duplicate_when_in_both(store, solar, bridge_state):
    """A channel present in both CCU3 discovery and config-store appears once only."""
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    device = Device(
        address="OEQ1",
        model="HM-LC-Sw1",
        channels=[Channel(address="OEQ1:1", hm_type="SWITCH", name="Channel 1")],
    )
    app = _make_app_with_ccu3(store, solar, bridge_state, [device])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/devices")
    data = r.json()
    addresses = [d["address"] for d in data]
    assert addresses.count("OEQ1:1") == 1


# ---------------------------------------------------------------------------
# POST /api/devices — invalid hk_type → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_device_invalid_hk_type_returns_422(app, store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/devices/OEQ9:1",
            json={"exported": True, "hk_type": "not_a_real_type", "name": "X"},
        )
    assert r.status_code == 422
    # nothing should have been persisted
    assert store.get_mapping("OEQ9:1") is None


# ---------------------------------------------------------------------------
# GET /api/solar — graceful when no snapshot yet (pv is None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_solar_none_snapshot_returns_unavailable(store, ccu3, bridge_state):
    """Before the first poll, solar_state.pv may be None — report unavailable, not 500."""
    class EmptySolarState:
        pv = None

    app = create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=EmptySolarState(),
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=EventBus(),
        log_buffer=RingBufferLogHandler(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/solar")
    assert r.status_code == 200
    assert r.json()["available"] is False


@pytest.mark.asyncio
async def test_post_device_publishes_config_changed(app, store, bus):
    received = []
    bus.subscribe("config.changed", lambda e: received.append(e))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/devices/OEQ7:1",
            json={"exported": True, "hk_type": "switch", "name": "Lamp"},
        )
    assert r.status_code == 200
    assert received == [{"address": "OEQ7:1"}]


# ---------------------------------------------------------------------------
# /api/control
# ---------------------------------------------------------------------------

def _control_app(store, ccu3, solar, bridge_state, hap_bridge):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=EventBus(),
        log_buffer=RingBufferLogHandler(),
        hap_bridge=hap_bridge,
    )


@pytest.mark.asyncio
async def test_get_control_returns_snapshot(store, ccu3, solar, bridge_state):
    app = _control_app(store, ccu3, solar, bridge_state, FakeHapBridge())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/control")
    assert r.status_code == 200
    devices = r.json()["devices"]
    assert devices[0]["address"] == "SW:1"
    assert devices[0]["state"] == {"on": False}


@pytest.mark.asyncio
async def test_post_control_dispatches_command(store, ccu3, solar, bridge_state):
    fake = FakeHapBridge()
    app = _control_app(store, ccu3, solar, bridge_state, fake)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/control/SW:1", json={"field": "on", "value": True})
    assert r.status_code == 200
    assert fake.calls == [("SW:1", "on", True)]


@pytest.mark.asyncio
async def test_post_control_not_controllable_returns_400(store, ccu3, solar, bridge_state):
    app = _control_app(store, ccu3, solar, bridge_state, FakeHapBridge())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/control/RO:1", json={"field": "open", "value": False})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_control_without_bridge_is_empty(app):
    # The default app fixture wires no hap_bridge → endpoint degrades gracefully.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/control")
    assert r.status_code == 200
    assert r.json() == {"devices": []}


# ---------------------------------------------------------------------------
# /api/config — backup / restore
# ---------------------------------------------------------------------------

def _backup_app(store, solar, bridge_state, bus, backup_dir=None):
    return create_app(
        config_store=store,
        ccu3_adapter=FakeCcu3Adapter(),
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=bus,
        log_buffer=RingBufferLogHandler(),
        backup_dir=backup_dir,
    )


@pytest.mark.asyncio
async def test_get_config_backup_downloads_json(store, solar, bridge_state, bus):
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    app = _backup_app(store, solar, bridge_state, bus)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/config/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.json() == store.export_config()


@pytest.mark.asyncio
async def test_post_config_restore_applies_and_publishes(store, solar, bridge_state, bus):
    received = []
    bus.subscribe("config.changed", lambda e: received.append(e))
    app = _backup_app(store, solar, bridge_state, bus)
    payload = {
        "version": 1,
        "mappings": [{"address": "Z:1", "exported": True,
                      "hk_type": "outlet", "name": "Restored"}],
        "aids": [{"address": "Z:1", "aid": 4}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/config/restore", json=payload)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "imported": 1}
    assert store.get_mapping("Z:1")["hk_type"] == HKType.OUTLET
    assert received == [{"restored": True}]


@pytest.mark.asyncio
async def test_post_config_restore_invalid_returns_422(store, solar, bridge_state, bus):
    app = _backup_app(store, solar, bridge_state, bus)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/config/restore", json={"nonsense": True})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_config_backups_lists_files(store, solar, bridge_state, bus, tmp_path):
    from homekit_bridge.backup import write_backup_file
    backup_dir = tmp_path / "backups"
    write_backup_file(store, backup_dir)
    app = _backup_app(store, solar, bridge_state, bus, backup_dir=backup_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/config/backups")
    assert r.status_code == 200
    backups = r.json()["backups"]
    assert len(backups) == 1
    assert backups[0]["name"].startswith("config-")


@pytest.mark.asyncio
async def test_download_named_backup(store, solar, bridge_state, bus, tmp_path):
    from homekit_bridge.backup import write_backup_file
    backup_dir = tmp_path / "backups"
    path = write_backup_file(store, backup_dir)
    app = _backup_app(store, solar, bridge_state, bus, backup_dir=backup_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/config/backups/{path.name}")
    assert r.status_code == 200
    assert r.json() == store.export_config()


@pytest.mark.asyncio
async def test_download_backup_rejects_path_traversal(store, solar, bridge_state, bus, tmp_path):
    app = _backup_app(store, solar, bridge_state, bus, backup_dir=tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/config/backups/..%2f..%2fetc%2fpasswd")
    assert r.status_code in (400, 404)
