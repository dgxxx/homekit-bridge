# QR-Pairing & Logging-Seite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zwei neue UI-Bereiche — ein Tab „Verbindung" mit scanbarem HomeKit-Pairing-QR (plus PIN/Status) und ein Tab „Logs" mit In-Memory-Ringpuffer, Level-Filter und Auto-Refresh.

**Architecture:** Ein `RingBufferLogHandler` am Root-Logger sammelt die letzten 500 Log-Zeilen im RAM. Drei neue FastAPI-Endpoints (`/api/pairing`, `/api/pairing/qr.svg`, `/api/logs`) unter der bestehenden Basic-Auth liefern Pairing-Daten (über Accessor-Methoden auf `_BridgeState`, die `driver.state.pincode` und `driver.accessory.xhm_uri()` lesen) bzw. Log-Records. Das Vanilla-JS-Frontend pollt wie gehabt.

**Tech Stack:** Python 3.12, FastAPI, HAP-python (`Accessory.xhm_uri()`), `qrcode` (SVG via `SvgPathImage`), stdlib `logging`/`collections.deque`, Vanilla JS.

**Spec:** `docs/superpowers/specs/2026-06-10-qr-pairing-and-logs-design.md`

---

## File Structure

- **Create:** `src/homekit_bridge/logbuffer.py` — `RingBufferLogHandler` (RAM-Ringpuffer, thread-sicher). Einzige Verantwortung: Log-Records puffern + gefiltert ausgeben.
- **Create:** `tests/test_logbuffer.py` — Unit-Tests für den Handler.
- **Create:** `tests/web/test_pairing_and_logs.py` — API-Tests für die drei neuen Endpoints.
- **Modify:** `src/homekit_bridge/__main__.py` — Ringpuffer am Root-Logger installieren, `log_buffer` in `AppComponents` + `create_app`; `_BridgeState` Pairing-Accessoren; `_log_pairing_info` auf `xhm_uri()` umstellen.
- **Modify:** `src/homekit_bridge/web/api.py` — neuer `log_buffer`-Parameter + drei Routen.
- **Modify:** `pyproject.toml` — `qrcode` als Laufzeit-Dependency.
- **Modify:** `tests/web/test_api.py` — bestehende `create_app`-Aufrufe um `log_buffer=` ergänzen.
- **Modify:** `tests/test_main_wiring.py` — `log_buffer`-Feld prüfen.
- **Modify:** `src/homekit_bridge/web/static/index.html` / `app.js` / `styles.css` — zwei Tabs + Views.

---

## Task 1: RingBufferLogHandler

**Files:**
- Create: `src/homekit_bridge/logbuffer.py`
- Test: `tests/test_logbuffer.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_logbuffer.py`:

```python
"""Unit tests for the in-memory ring buffer log handler."""

import logging

from homekit_bridge.logbuffer import RingBufferLogHandler


def _log(handler, level, msg, name="test"):
    record = logging.LogRecord(name, level, __file__, 0, msg, None, None)
    handler.emit(record)


def test_records_capture_shape():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.INFO, "hello", name="ccu3")
    recs = h.records()
    assert len(recs) == 1
    r = recs[0]
    assert r["level"] == "INFO"
    assert r["logger"] == "ccu3"
    assert r["message"] == "hello"
    assert isinstance(r["ts"], float)


def test_maxlen_eviction():
    h = RingBufferLogHandler(capacity=3)
    for i in range(5):
        _log(h, logging.INFO, f"m{i}")
    assert [r["message"] for r in h.records()] == ["m2", "m3", "m4"]


def test_level_filter_is_gte():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.DEBUG, "d")
    _log(h, logging.INFO, "i")
    _log(h, logging.WARNING, "w")
    _log(h, logging.ERROR, "e")
    assert [r["message"] for r in h.records(level="WARNING")] == ["w", "e"]


def test_limit_keeps_last_n():
    h = RingBufferLogHandler(capacity=10)
    for i in range(5):
        _log(h, logging.INFO, f"m{i}")
    assert [r["message"] for r in h.records(limit=2)] == ["m3", "m4"]


def test_unknown_level_means_no_filter():
    h = RingBufferLogHandler(capacity=10)
    _log(h, logging.INFO, "i")
    assert len(h.records(level="BOGUS")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_logbuffer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'homekit_bridge.logbuffer'`

- [ ] **Step 3: Write the implementation**

`src/homekit_bridge/logbuffer.py`:

```python
"""In-memory ring buffer logging handler for the web log viewer.

Keeps the most recent log records in a bounded, thread-safe deque so the web
API can expose them at /api/logs.  No persistence — the buffer is RAM only and
resets on restart.
"""

import collections
import logging
import threading

DEFAULT_CAPACITY = 500


class RingBufferLogHandler(logging.Handler):
    """A logging.Handler that keeps the last *capacity* records in memory."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._buf: collections.deque[dict] = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        except Exception:
            self.handleError(record)
            return
        with self._lock:
            self._buf.append(entry)

    def records(self, level: str | None = None, limit: int | None = None) -> list[dict]:
        """Return buffered records oldest-first.

        *level* (if given and valid) keeps only records at or above that level —
        e.g. ``"WARNING"`` yields WARNING/ERROR/CRITICAL.  An unknown level string
        is treated as no filter.  *limit* keeps only the last N records.
        """
        with self._lock:
            items = list(self._buf)
        if level:
            threshold = logging.getLevelName(level.upper())
            if isinstance(threshold, int):
                items = [
                    r for r in items
                    if logging.getLevelName(r["level"]) >= threshold
                ]
        if limit is not None:
            items = items[-limit:]
        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_logbuffer.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
ruff check --fix src/homekit_bridge/logbuffer.py tests/test_logbuffer.py
git add src/homekit_bridge/logbuffer.py tests/test_logbuffer.py
git commit -m "feat: in-memory ring buffer log handler"
```

---

## Task 2: Wire log_buffer + pairing accessors into __main__ and create_app

This task threads the new `log_buffer` through `build()` → `AppComponents` → `create_app`, adds pairing accessor methods to `_BridgeState`, and fixes `_log_pairing_info` to use the real `xhm_uri()`. It updates the existing `create_app` signature, so all existing call sites (production + tests) are updated in the same commit to keep the suite green. No new endpoint yet — the param is plumbed but unused until Task 3/4.

**Files:**
- Modify: `src/homekit_bridge/__main__.py`
- Modify: `src/homekit_bridge/web/api.py:107` (signature only)
- Modify: `tests/web/test_api.py` (5 call sites)
- Test: `tests/test_main_wiring.py`

- [ ] **Step 1: Write the failing wiring test**

Append to `tests/test_main_wiring.py`:

```python
def test_build_exposes_log_buffer(tmp_path, monkeypatch):
    """build() installs a RingBufferLogHandler and exposes it on AppComponents."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(fakes={"mqtt_client": FakeMqttClient()})

    from homekit_bridge.logbuffer import RingBufferLogHandler
    assert isinstance(components.log_buffer, RingBufferLogHandler)
    # The handler is attached to the root logger so it captures all output.
    assert components.log_buffer in logging.getLogger().handlers


def test_bridge_state_pairing_accessors(tmp_path, monkeypatch):
    """_BridgeState exposes the real PIN and xhm:// pairing URI from the driver."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    components = build(fakes={"mqtt_client": FakeMqttClient()})

    bs = components.bridge_state
    assert isinstance(bs.pairing_pin(), str)
    assert bs.pairing_uri().startswith("X-HM://")
```

Add the missing import at the top of `tests/test_main_wiring.py`:

```python
import logging
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main_wiring.py -q`
Expected: FAIL — `AppComponents` has no `log_buffer` / `_BridgeState` has no `pairing_pin`.

- [ ] **Step 3: Add pairing accessors to `_BridgeState`**

In `src/homekit_bridge/__main__.py`, inside class `_BridgeState`, after the `ccu3_connected` property (around line 96), add:

```python
    def pairing_pin(self) -> Optional[str]:
        """The HomeKit setup PIN as a string, or None if not available yet."""
        if self.hap_driver is None:
            return None
        try:
            return self.hap_driver.state.pincode.decode()
        except Exception:
            return None

    def pairing_uri(self) -> Optional[str]:
        """The X-HM:// pairing URI for the QR code, or None if not available."""
        if self.hap_driver is None:
            return None
        try:
            return self.hap_driver.accessory.xhm_uri()
        except Exception:
            return None
```

- [ ] **Step 4: Add `log_buffer` plumbing to `build()` / `AppComponents`**

In `src/homekit_bridge/__main__.py`:

Add the import near the other `homekit_bridge` imports (around line 24):

```python
from homekit_bridge.logbuffer import RingBufferLogHandler
```

Add a field to `AppComponents` (place it directly after `bridge_state: _BridgeState`, before `stop_event`):

```python
    log_buffer: RingBufferLogHandler = field(default_factory=RingBufferLogHandler)
```

Add a helper above `build()`:

```python
def _install_log_buffer() -> RingBufferLogHandler:
    """Attach a fresh ring buffer to the root logger (replacing any prior one).

    Replacing avoids stacking duplicate handlers when build() runs repeatedly
    (e.g. across tests in one process).
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, RingBufferLogHandler):
            root.removeHandler(existing)
    handler = RingBufferLogHandler()
    root.addHandler(handler)
    return handler
```

In `build()`, after `bus = EventBus()` (around line 134) add:

```python
    log_buffer = _install_log_buffer()
```

Update the `create_app(...)` call in `build()` to pass it:

```python
    app = create_app(
        config_store=config_store,
        ccu3_adapter=ccu3_adapter,
        solar_state=solar_state,
        bridge_state=bridge_state,
        settings=settings,
        bus=bus,
        log_buffer=log_buffer,
    )
```

Update the `return AppComponents(...)` to include it (add after `bridge_state=bridge_state,`):

```python
        log_buffer=log_buffer,
```

- [ ] **Step 5: Fix `_log_pairing_info` to use the real URI**

In `src/homekit_bridge/__main__.py`, replace the whole `_log_pairing_info` function and delete `_encode_setup_id`:

```python
def _log_pairing_info(driver: AccessoryDriver) -> None:
    """Print the HAP pairing PIN (and an ASCII QR if qrcode is available)."""
    try:
        pin = driver.state.pincode.decode()
        logger.info("HomeKit pairing PIN: %s", pin)
        try:
            import qrcode  # type: ignore[import-untyped]
            qr = qrcode.QRCode()
            qr.add_data(driver.accessory.xhm_uri())
            qr.print_ascii(invert=True)
        except Exception:
            pass  # qrcode optional / accessory not ready
    except Exception:
        logger.debug("Could not read HAP pairing PIN", exc_info=True)
```

- [ ] **Step 6: Add the `log_buffer` parameter to `create_app`**

In `src/homekit_bridge/web/api.py`, change the signature (around line 107) to add the parameter after `bus`:

```python
def create_app(
    config_store: ConfigStore,
    ccu3_adapter: Any,
    solar_state: Any,
    bridge_state: Any,
    settings: Settings,
    bus: EventBus,
    log_buffer: Any,
) -> FastAPI:
```

(No route uses it yet — that comes in Task 3. The param is accepted and ignored for now.)

- [ ] **Step 7: Update existing `create_app` call sites in tests**

In `tests/web/test_api.py`, add a fixture near the other fixtures (after the `bus` fixture, ~line 84):

```python
@pytest.fixture
def logbuf():
    from homekit_bridge.logbuffer import RingBufferLogHandler
    return RingBufferLogHandler()
```

Update the `app` fixture (add the param to the signature and the call):

```python
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
```

Update the `auth_app` fixture the same way:

```python
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
```

Update `_make_app_with_ccu3` to add `log_buffer`:

```python
def _make_app_with_ccu3(store, solar, bridge_state, devices):
    from homekit_bridge.logbuffer import RingBufferLogHandler
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
```

In `test_get_devices_ccu3_failure_returns_config_only`, add `log_buffer=RingBufferLogHandler()` to the inline `create_app(...)` call and import the handler at the top of that test body:

```python
    from homekit_bridge.logbuffer import RingBufferLogHandler
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
```

In `test_get_solar_none_snapshot_returns_unavailable`, add the same to its inline `create_app(...)`:

```python
    from homekit_bridge.logbuffer import RingBufferLogHandler
    app = create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=EmptySolarState(),
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=EventBus(),
        log_buffer=RingBufferLogHandler(),
    )
```

- [ ] **Step 8: Run the affected tests**

Run: `pytest tests/test_main_wiring.py tests/web/test_api.py -q`
Expected: PASS (all existing web tests + 2 new wiring tests green)

- [ ] **Step 9: Commit**

```bash
ruff check --fix src tests
git add src/homekit_bridge/__main__.py src/homekit_bridge/web/api.py tests/test_main_wiring.py tests/web/test_api.py
git commit -m "feat: plumb log buffer + pairing accessors through build/create_app"
```

---

## Task 3: GET /api/logs endpoint

**Files:**
- Modify: `src/homekit_bridge/web/api.py`
- Test: `tests/web/test_pairing_and_logs.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_pairing_and_logs.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/web/test_pairing_and_logs.py -q -k logs`
Expected: FAIL with 404 (route not defined yet)

- [ ] **Step 3: Implement the route**

In `src/homekit_bridge/web/api.py`, after the `/api/status` route block (around line 188, before the static mount), add:

```python
    # ------------------------------------------------------------------
    # /api/logs
    # ------------------------------------------------------------------

    @app.get("/api/logs", dependencies=api_deps)
    async def get_logs(level: Optional[str] = None) -> dict:
        return {"records": log_buffer.records(level=level)}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/web/test_pairing_and_logs.py -q -k logs`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
ruff check --fix src tests
git add src/homekit_bridge/web/api.py tests/web/test_pairing_and_logs.py
git commit -m "feat: GET /api/logs endpoint backed by ring buffer"
```

---

## Task 4: Pairing endpoints + qrcode dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/homekit_bridge/web/api.py`
- Test: `tests/web/test_pairing_and_logs.py` (append)

- [ ] **Step 1: Add `qrcode` as a runtime dependency**

In `pyproject.toml`, add to the `dependencies` list (after `"pydantic>=2.6",`):

```toml
    "qrcode>=7.4",
```

Then ensure it is installed in the dev environment:

Run: `pip install -e '.[dev]'`
Expected: installs `qrcode` (and its `pypng` dep) successfully.

- [ ] **Step 2: Write the failing tests**

Append to `tests/web/test_pairing_and_logs.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/web/test_pairing_and_logs.py -q -k pairing`
Expected: FAIL with 404 (routes not defined)

- [ ] **Step 4: Implement the routes**

In `src/homekit_bridge/web/api.py`, add `Response` to the FastAPI import (line 27):

```python
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
```

Add an `io` import at the top (with the stdlib imports, around line 22):

```python
import io
```

After the `/api/logs` route added in Task 3 (before the static mount), add:

```python
    # ------------------------------------------------------------------
    # /api/pairing — HomeKit setup PIN + QR
    # ------------------------------------------------------------------

    @app.get("/api/pairing", dependencies=api_deps)
    async def get_pairing() -> dict:
        pin = bridge_state.pairing_pin()
        uri = bridge_state.pairing_uri()
        if pin is None or uri is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pairing information not available yet",
            )
        return {"pin": pin, "uri": uri, "paired": bridge_state.paired}

    @app.get("/api/pairing/qr.svg", dependencies=api_deps)
    async def get_pairing_qr() -> Response:
        uri = bridge_state.pairing_uri()
        if uri is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pairing information not available yet",
            )
        try:
            import qrcode
            import qrcode.image.svg
            img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
            buf = io.BytesIO()
            img.save(buf)
        except Exception:
            logger.exception("Failed to render pairing QR code")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="QR rendering failed",
            )
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/web/test_pairing_and_logs.py -q`
Expected: PASS (all logs + pairing tests green)

- [ ] **Step 6: Commit**

```bash
ruff check --fix src tests
git add pyproject.toml src/homekit_bridge/web/api.py tests/web/test_pairing_and_logs.py
git commit -m "feat: pairing endpoints (PIN + xhm uri + SVG QR)"
```

---

## Task 5: Frontend — Verbindung + Logs tabs

No automated frontend tests exist in this project (pure Vanilla JS, no build step), so this task ends with a manual verification step instead of pytest.

**Files:**
- Modify: `src/homekit_bridge/web/static/index.html`
- Modify: `src/homekit_bridge/web/static/app.js`
- Modify: `src/homekit_bridge/web/static/styles.css`

- [ ] **Step 1: Add the two nav tabs**

In `index.html`, inside `<div class="nav__tabs" role="tablist">` (after the Solar tab button, ~line 46), add:

```html
      <button
        class="nav__tab"
        role="tab"
        aria-selected="false"
        aria-controls="view-pairing"
        id="tab-pairing"
        data-view="pairing"
      >Verbindung</button>

      <button
        class="nav__tab"
        role="tab"
        aria-selected="false"
        aria-controls="view-logs"
        id="tab-logs"
        data-view="logs"
      >Logs</button>
```

- [ ] **Step 2: Add the two view panels**

In `index.html`, after the closing `</section>` of `view-solar` and before `</main>` (~line 176), add:

```html
    <!-- ----- View: Verbindung ----- -->
    <section
      class="view"
      id="view-pairing"
      role="tabpanel"
      aria-labelledby="tab-pairing"
    >
      <h1 class="pairing__heading">Mit HomeKit verbinden</h1>
      <div class="pairing-card" id="pairing-card">
        <div class="pairing-card__qr">
          <img id="pairing-qr" alt="HomeKit Pairing QR-Code" />
        </div>
        <div class="pairing-card__info">
          <p class="pairing-card__status" id="pairing-status">Lade&#8230;</p>
          <p class="pairing-card__pin-label">Setup-Code</p>
          <p class="pairing-card__pin" id="pairing-pin">&#8212;</p>
          <p class="pairing-card__hint">
            Home-App &rarr; Ger&auml;t hinzuf&uuml;gen &rarr; QR-Code scannen
            oder Code manuell eingeben.
          </p>
        </div>
      </div>
    </section>

    <!-- ----- View: Logs ----- -->
    <section
      class="view"
      id="view-logs"
      role="tabpanel"
      aria-labelledby="tab-logs"
    >
      <div class="logs__toolbar">
        <h1 class="logs__heading">Logs</h1>
        <label class="logs__filter" for="log-level">
          Level:
          <select id="log-level">
            <option value="">Alle</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO" selected>INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </label>
      </div>
      <div class="log-viewer" id="log-viewer" aria-live="polite">
        <div class="state-message">Lade Logs&#8230;</div>
      </div>
    </section>
```

- [ ] **Step 3: Add the pairing + logs JS**

In `app.js`, extend the `state` object (in section 1) — add these properties:

```javascript
  /** @type {null|{pin:string, uri:string, paired:boolean}} */
  pairing: null,

  /** @type {Array<{ts:number, level:string, logger:string, message:string}>} */
  logs: [],

  /** current log level filter */
  logLevel: "INFO",
```

Add a new functions block before the polling/lifecycle section (section 8):

```javascript
/* =================================================================
   Pairing view
   ================================================================= */

async function fetchPairing() {
  try {
    state.pairing = await apiFetch("/api/pairing");
  } catch (err) {
    state.pairing = null;
  }
  renderPairing();
}

function renderPairing() {
  const statusEl = document.getElementById("pairing-status");
  const pinEl = document.getElementById("pairing-pin");
  const qrEl = document.getElementById("pairing-qr");
  if (!statusEl || !pinEl || !qrEl) return;

  if (!state.pairing) {
    statusEl.textContent = "Pairing-Info nicht verfügbar";
    pinEl.textContent = "—";
    qrEl.removeAttribute("src");
    return;
  }
  statusEl.textContent = state.pairing.paired ? "Gekoppelt" : "Nicht gekoppelt";
  statusEl.classList.toggle("is-paired", state.pairing.paired);
  pinEl.textContent = state.pairing.pin;
  // Cache-bust so a re-render after re-pairing reloads a fresh QR.
  qrEl.src = "/api/pairing/qr.svg?ts=" + Date.now();
}

/* =================================================================
   Logs view
   ================================================================= */

async function fetchLogs() {
  const q = state.logLevel ? "?level=" + encodeURIComponent(state.logLevel) : "";
  try {
    const data = await apiFetch("/api/logs" + q);
    state.logs = data.records || [];
  } catch (err) {
    state.logs = [];
  }
  renderLogs();
}

function renderLogs() {
  const viewer = document.getElementById("log-viewer");
  if (!viewer) return;
  if (state.logs.length === 0) {
    viewer.innerHTML = '<div class="state-message">Keine Log-Einträge</div>';
    return;
  }
  viewer.innerHTML = state.logs.map((r) => {
    const t = new Date(r.ts * 1000).toLocaleTimeString("de-DE");
    return (
      '<div class="log-line log-line--' + r.level + '">' +
      '<span class="log-line__ts">' + t + "</span>" +
      '<span class="log-line__level">' + r.level + "</span>" +
      '<span class="log-line__logger">' + escapeHtml(r.logger) + "</span>" +
      '<span class="log-line__msg">' + escapeHtml(r.message) + "</span>" +
      "</div>"
    );
  }).join("");
  viewer.scrollTop = viewer.scrollHeight;
}
```

`app.js` has no `escapeHtml` helper (confirmed via grep), so add this to the
Utilities block near the bottom of the file (after `startPolling`, ~line 650):

```javascript
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
```

Note: the existing fetch helper is `apiFetch(path, opts)` (line 65) and it
already returns parsed JSON — the snippets above call it directly.

- [ ] **Step 4: Wire the new views into navigation + polling**

In `app.js`, update the `switchView(viewId)` function (line 131). First widen its
JSDoc type comment (line ~129) to include the new views:

```javascript
/**
 * @param {"dashboard"|"devices"|"solar"|"pairing"|"logs"} viewId
 */
```

Then, at the **end** of `switchView` (after the `.view` panels are toggled,
~line 145), add a one-shot fetch when entering each new view:

```javascript
  if (viewId === "pairing") fetchPairing();
  if (viewId === "logs") fetchLogs();
```

In `poll()` (line 578) — alongside the existing `if (state.activeView === "dashboard")`
and `"solar"` re-render blocks (~line 596) — add a logs refresh so logs auto-refresh
only while their tab is open:

```javascript
    if (state.activeView === "logs") {
      fetchLogs();
    }
```

Wire the level-filter `<select>` once at startup. In the `DOMContentLoaded`
handler (line 677), after `startPolling();`, add:

```javascript
  const logLevelEl = document.getElementById("log-level");
  if (logLevelEl) {
    state.logLevel = logLevelEl.value;
    logLevelEl.addEventListener("change", () => {
      state.logLevel = logLevelEl.value;
      fetchLogs();
    });
  }
```

- [ ] **Step 5: Add styles**

In `styles.css`, append (using the file's existing CSS custom properties where present — adjust var names to match the file's palette if they differ):

```css
/* ---- Pairing view ---- */
.pairing-card {
  display: flex;
  flex-wrap: wrap;
  gap: 2rem;
  align-items: center;
  background: var(--surface, #fff);
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
.pairing-card__qr {
  background: #fff;
  padding: 1rem;
  border-radius: 8px;
}
.pairing-card__qr img {
  display: block;
  width: 240px;
  height: 240px;
}
.pairing-card__pin {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  font-family: ui-monospace, monospace;
  margin: 0.25rem 0 1rem;
}
.pairing-card__pin-label,
.pairing-card__hint {
  color: var(--text-muted, #667);
  margin: 0;
}
.pairing-card__status.is-paired {
  color: var(--ok, #2a8a4a);
  font-weight: 600;
}

/* ---- Logs view ---- */
.logs__toolbar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}
.log-viewer {
  margin-top: 1rem;
  max-height: 65vh;
  overflow-y: auto;
  background: #0f1115;
  color: #d6d9df;
  border-radius: 8px;
  padding: 0.75rem;
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
  line-height: 1.5;
}
.log-line {
  display: grid;
  grid-template-columns: 5.5rem 4.5rem 9rem 1fr;
  gap: 0.5rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.log-line__ts { color: #7f8694; }
.log-line__logger { color: #8aa9c0; }
.log-line--WARNING .log-line__level { color: #e0a042; }
.log-line--ERROR .log-line__level,
.log-line--CRITICAL .log-line__level { color: #e05656; }
.log-line--INFO .log-line__level { color: #5aa9e0; }
.log-line--DEBUG .log-line__level { color: #7f8694; }
```

- [ ] **Step 6: Manual verification**

Run the suite to confirm nothing broke:

Run: `pytest -q`
Expected: PASS (all tests, including the new ones)

Then verify the UI manually:

```bash
STATE_DIR=./state python3 -m homekit_bridge
```

Open `http://localhost:8095`:
- Tab „Verbindung": a QR code renders, PIN is shown, status reads „Nicht gekoppelt".
- Scan the QR with the iOS Home app → it offers to add the bridge (confirms the URI is valid).
- Tab „Logs": log lines appear, the level filter narrows them, and new lines show up within ~5 s without reload.

- [ ] **Step 7: Commit**

```bash
ruff check --fix src tests
git add src/homekit_bridge/web/static/
git commit -m "feat: Verbindung (QR/PIN) and Logs tabs in web UI"
```

---

## Final verification

- [ ] Run the full suite + lint (Definition of Done):

```bash
ruff check src tests
pytest -q
```

Expected: `ruff check` clean (no F401/E/W), all tests pass.

- [ ] Update `CLAUDE.md` „Projektstatus" test count if it is referenced elsewhere (the doc currently says „103 Tests grün"; bump to the new total after this plan).
