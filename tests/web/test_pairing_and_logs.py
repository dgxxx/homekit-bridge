"""Tests for the pairing and logs API routes."""

import base64
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.logbuffer import RingBufferLogHandler
from homekit_bridge.models import PVData
from homekit_bridge.settings import Settings
from homekit_bridge.web.api import create_app


class FakeCcu3Adapter:
    def list_devices(self):
        return []

    def set_value(self, address, key, value):
        pass


class FakeSolarState:
    pv = PVData()


class FakeBridgeState:
    """Pairing info available."""
    paired = False

    def pairing_pin(self):
        return "123-45-678"

    def pairing_uri(self):
        return "X-HM://0012ABCDEFGHK"


class UnavailableBridgeState:
    """Pairing info not ready yet (HAP not started)."""
    paired = False

    def pairing_pin(self):
        return None

    def pairing_uri(self):
        return None


def _make_app(tmp_path, bridge_state, log_buffer=None, web_password=None):
    return create_app(
        config_store=ConfigStore(tmp_path / "t.db"),
        ccu3_adapter=FakeCcu3Adapter(),
        solar_state=FakeSolarState(),
        bridge_state=bridge_state,
        settings=Settings(web_password=web_password),
        bus=EventBus(),
        log_buffer=log_buffer or RingBufferLogHandler(),
    )


# ---- /api/logs ----

@pytest.mark.asyncio
async def test_logs_returns_records(tmp_path):
    buf = RingBufferLogHandler()
    buf.emit(logging.LogRecord("ccu3", logging.INFO, __file__, 0, "hi", None, None))
    app = _make_app(tmp_path, FakeBridgeState(), log_buffer=buf)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs")
    assert r.status_code == 200
    recs = r.json()["records"]
    assert len(recs) == 1
    assert recs[0]["message"] == "hi"
    assert recs[0]["logger"] == "ccu3"
    assert set(recs[0]) == {"ts", "level", "logger", "message"}


@pytest.mark.asyncio
async def test_logs_empty_buffer(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs")
    assert r.status_code == 200
    assert r.json() == {"records": []}


@pytest.mark.asyncio
async def test_logs_level_filter(tmp_path):
    buf = RingBufferLogHandler()
    buf.emit(logging.LogRecord("x", logging.INFO, __file__, 0, "i", None, None))
    buf.emit(logging.LogRecord("x", logging.ERROR, __file__, 0, "e", None, None))
    app = _make_app(tmp_path, FakeBridgeState(), log_buffer=buf)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?level=WARNING")
    msgs = [rec["message"] for rec in r.json()["records"]]
    assert msgs == ["e"]


@pytest.mark.asyncio
async def test_logs_requires_auth(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState(), web_password="secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs")
    assert r.status_code == 401


# ---- /api/pairing ----

@pytest.mark.asyncio
async def test_pairing_returns_pin_and_uri(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/pairing")
    assert r.status_code == 200
    data = r.json()
    assert data["pin"] == "123-45-678"
    assert data["uri"] == "X-HM://0012ABCDEFGHK"
    assert data["paired"] is False


@pytest.mark.asyncio
async def test_pairing_503_when_unavailable(tmp_path):
    app = _make_app(tmp_path, UnavailableBridgeState())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/pairing")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_pairing_qr_svg(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/pairing/qr.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content


@pytest.mark.asyncio
async def test_pairing_qr_503_when_unavailable(tmp_path):
    app = _make_app(tmp_path, UnavailableBridgeState())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/pairing/qr.svg")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_pairing_requires_auth(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState(), web_password="secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/api/pairing")
        r2 = await c.get("/api/pairing/qr.svg")
    assert r1.status_code == 401
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_pairing_qr_svg_with_auth(tmp_path):
    app = _make_app(tmp_path, FakeBridgeState(), web_password="secret")
    creds = base64.b64encode(b"admin:secret").decode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/pairing/qr.svg", headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 200
    assert b"<svg" in r.content
