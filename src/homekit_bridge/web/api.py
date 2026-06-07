"""FastAPI application factory for homekit-bridge.

``create_app(config_store, ccu3_adapter, solar_state, bridge_state, settings)``
builds and returns the ASGI app.  All dependencies are injected so the app
can be tested without real adapters.

Routes
------
GET  /health                    — liveness probe, always 200, no auth
GET  /api/devices               — list of all known channel mappings
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from homekit_bridge.config import ConfigStore
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
    exported: bool
    hk_type: Optional[str] = None
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
        # Merge: all known channels from CCU3 discovery + store mappings
        # For now return whatever is in the config store (CCU3 discovery
        # is kicked off by the adapter; this endpoint just reads the DB).
        mappings = config_store.list_exported()
        # Also include non-exported stored mappings so the UI can manage them
        all_rows = _all_mappings(config_store)
        result = []
        for row in all_rows:
            result.append({
                "address": row["address"],
                "exported": row["exported"],
                "hk_type": row["hk_type"].value if row["hk_type"] else None,
                "name": row["name"],
            })
        return result

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
        return {"status": "ok", "address": address}

    # ------------------------------------------------------------------
    # /api/solar
    # ------------------------------------------------------------------

    @app.get("/api/solar", response_model=SolarOut, dependencies=api_deps)
    async def get_solar() -> dict:
        pv: PVData = solar_state.pv
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

def _all_mappings(store: ConfigStore) -> list[dict]:
    """Return every row in the mappings table (exported + non-exported).

    Uses the store's internal connection but delegates deserialization to the
    same ``_row_to_dict`` helper that ``get_mapping`` and ``list_exported`` use.
    """
    from homekit_bridge.config import _row_to_dict  # same package — not a layer violation

    with store._lock:
        rows = store._conn.execute(
            "SELECT * FROM mappings ORDER BY address"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]
