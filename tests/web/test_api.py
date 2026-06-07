"""Tests for the FastAPI web API.

Uses httpx.TestClient with injected fakes for ConfigStore, Ccu3Adapter,
solar state, and Settings.
"""

import base64
import pytest
from httpx import ASGITransport, AsyncClient

from homekit_bridge.config import ConfigStore
from homekit_bridge.models import HKType, PVData
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


# ---------------------------------------------------------------------------
# Settings fixture helpers
# ---------------------------------------------------------------------------

def _make_settings(web_password=None):
    return Settings(
        ccu3_host="192.168.1.10",
        solaredge_host="192.168.1.20",
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
def app(store, ccu3, solar, bridge_state):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
    )


@pytest.fixture
def auth_app(store, ccu3, solar, bridge_state):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(web_password="secret"),
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
