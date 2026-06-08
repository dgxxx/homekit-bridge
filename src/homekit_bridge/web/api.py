"""FastAPI application factory for homekit-bridge.

``create_app(config_store, ccu3_adapter, solar_state, bridge_state, settings)``
builds and returns the ASGI app.  All dependencies are injected so the app
can be tested without real adapters.

Routes
------
GET  /health                    — liveness probe, always 200, no auth
GET  /api/devices               — merged list: CCU3 discovery + config-store overrides
POST /api/devices/{address}     — upsert channel mapping (export / hk_type / name)
GET  /api/solar                 — latest PVData snapshot
GET  /api/status                — bridge + connectivity summary
GET  /                          — serves the static frontend (StaticFiles)

Auth
----
When ``settings.web_password`` is set, all /api/* routes require HTTP Basic
auth with any username and the configured password.  /health is always open.
"""

import base64
import logging
import pathlib
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.mapper.device_mapper import auto_hk_type
from homekit_bridge.models import HKType, PVData
from homekit_bridge.settings import Settings

logger = logging.getLogger(__name__)

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class DeviceMappingIn(BaseModel):
    exported: bool
    hk_type: Optional[str] = None
    name: str


class DeviceMappingOut(BaseModel):
    address: str
    type: str = ""                   # raw Homematic channel type (e.g. "SWITCH")
    exported: bool
    hk_type: Optional[str] = None    # config override
    suggested_hk_type: Optional[str] = None  # auto-detected from HM type
    name: str


class SolarOut(BaseModel):
    power_w: float
    energy_today_kwh: float
    battery_pct: Optional[int]
    producing: bool
    available: bool


class StatusOut(BaseModel):
    paired: bool
    accessory_count: int
    ccu3_connected: bool
    solaredge_connected: bool


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _make_auth_dependency(password: str):
    def _check(request: Request) -> None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic realm=\"homekit-bridge\""},
            )
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, _, supplied = decoded.partition(":")
        except Exception:
            supplied = ""
        if supplied != password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic realm=\"homekit-bridge\""},
            )
    return _check


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    config_store: ConfigStore,
    ccu3_adapter: Any,
    solar_state: Any,
    bridge_state: Any,
    settings: Settings,
    bus: EventBus,
) -> FastAPI:
    """Return the configured FastAPI application."""

    app = FastAPI(title="HomeKit Bridge", version="0.1.0")

    # Optional auth dependency for /api/* routes
    api_deps: list = []
    if settings.web_password:
        api_deps.append(Depends(_make_auth_dependency(settings.web_password)))

    # ------------------------------------------------------------------
    # /health — always open, no auth
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # /api/devices
    # ------------------------------------------------------------------

    @app.get("/api/devices", response_model=list[DeviceMappingOut], dependencies=api_deps)
    async def get_devices() -> list[dict]:
        return _merged_device_list(config_store, ccu3_adapter)

    @app.post("/api/devices/{address}", dependencies=api_deps)
    async def post_device(address: str, body: DeviceMappingIn) -> dict:
        hk_type: Optional[HKType] = None
        if body.hk_type is not None:
            try:
                hk_type = HKType(body.hk_type)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown hk_type: {body.hk_type!r}",
                )
        config_store.set_mapping(
            address,
            exported=body.exported,
            hk_type=hk_type,
            name=body.name,
        )
        bus.publish("config.changed", {"address": address})
        return {"status": "ok", "address": address}

    # ------------------------------------------------------------------
    # /api/solar
    # ------------------------------------------------------------------

    @app.get("/api/solar", response_model=SolarOut, dependencies=api_deps)
    async def get_solar() -> dict:
        # Before the first poll completes solar_state.pv may be None — report
        # an "unavailable" snapshot instead of crashing with a 500.
        pv: PVData = solar_state.pv if solar_state.pv is not None else PVData(available=False)
        return {
            "power_w": pv.power_w,
            "energy_today_kwh": pv.energy_today_kwh,
            "battery_pct": pv.battery_pct,
            "producing": pv.producing,
            "available": pv.available,
        }

    # ------------------------------------------------------------------
    # /api/status
    # ------------------------------------------------------------------

    @app.get("/api/status", response_model=StatusOut, dependencies=api_deps)
    async def get_status() -> dict:
        return {
            "paired": bridge_state.paired,
            "accessory_count": bridge_state.accessory_count,
            "ccu3_connected": bridge_state.ccu3_connected,
            "solaredge_connected": bridge_state.solaredge_connected,
        }

    # ------------------------------------------------------------------
    # Static frontend — mount last so API routes take priority
    # ------------------------------------------------------------------

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _all_config_mappings(store: ConfigStore) -> dict[str, dict]:
    """Return all config-store rows keyed by address."""
    return {row["address"]: row for row in store.list_all()}


def _merged_device_list(store: ConfigStore, ccu3_adapter: Any) -> list[dict]:
    """Merge CCU3-discovered channels with config-store overrides.

    Priority rules per channel:
    - ``type``: always from CCU3 discovery (raw HM type); empty string if config-only
    - ``name``: config override if set, else CCU3 channel name, else address
    - ``exported``: config value if present, else False
    - ``hk_type``: explicit config override (may be None)
    - ``suggested_hk_type``: auto_hk_type(raw_hm_type) — helps the UI pre-fill
    - Config-only channels (no CCU3 discovery entry) are still included as-is
    - If CCU3 discovery fails, falls back to config-only (graceful)
    """
    config: dict[str, dict] = _all_config_mappings(store)

    # Build address → (hm_type, ccu3_name) from CCU3 discovery
    discovered: dict[str, tuple[str, str]] = {}
    try:
        for device in ccu3_adapter.list_devices():
            for ch in device.channels:
                discovered[ch.address] = (ch.hm_type, ch.name)
    except Exception:
        logger.warning("CCU3 list_devices() failed — falling back to config-only device list")

    # Union of all known addresses
    all_addresses = sorted(set(config) | set(discovered))

    result = []
    for address in all_addresses:
        hm_type, ccu3_name = discovered.get(address, ("", ""))
        row = config.get(address)

        # Resolve fields with priority: config > discovery > defaults
        exported = row["exported"] if row else False
        hk_type_obj = row["hk_type"] if row else None
        name = (row["name"] if row and row["name"] else None) or ccu3_name or address

        suggested = auto_hk_type(hm_type) if hm_type else None

        result.append({
            "address": address,
            "type": hm_type,
            "exported": exported,
            "hk_type": hk_type_obj.value if hk_type_obj else None,
            "suggested_hk_type": suggested.value if suggested else None,
            "name": name,
        })

    return result
