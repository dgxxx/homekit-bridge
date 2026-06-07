# HomeKit-Bridge (CCU3 & SolarEdge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized Python service that exposes Homematic CCU3 devices (read + switch) and SolarEdge PV live data (read-only) as HomeKit accessories, configurable via a web UI — a replacement for the CCU3 HomeKit plugin.

**Architecture:** A single Python process runs four cooperating subsystems coordinated via an in-process event bus / shared state: `ccu3_adapter` (XML-RPC client + callback server), `solaredge_adapter` (Modbus poller), `device_mapper` (translates source devices/values to HomeKit accessory definitions), and `hap_bridge` (HAP-python bridge). A FastAPI app serves the config API and a Vanilla-JS frontend. Mappings/names persist in SQLite; secrets come from env vars.

**Tech Stack:** Python 3.12, HAP-python, pymodbus, FastAPI + Uvicorn, SQLite (stdlib `sqlite3`), pytest, Docker.

---

## File Structure

```
homekit/
├── pyproject.toml                 # deps + pytest/ruff config
├── Dockerfile
├── docker-compose.yml             # host network mode, volume for state
├── .env.example
├── README.md
├── src/homekit_bridge/
│   ├── __init__.py
│   ├── __main__.py                # entrypoint: wires everything, starts loop
│   ├── config.py                  # SQLite-backed config store
│   ├── settings.py                # env-var settings (CCU3 host, SE host, web pw)
│   ├── events.py                  # simple in-process event bus + StateChange type
│   ├── models.py                  # dataclasses: Device, Channel, HKMapping, PVData
│   ├── ccu3/
│   │   ├── __init__.py
│   │   ├── client.py              # XML-RPC client wrapper (getValue/setValue/discovery)
│   │   ├── callback.py            # XML-RPC callback server (receives events)
│   │   └── adapter.py             # orchestrates client+callback, reconnect/backoff
│   ├── solaredge/
│   │   ├── __init__.py
│   │   ├── registers.py           # Modbus register map constants
│   │   └── adapter.py             # pymodbus poller -> PVData -> event bus
│   ├── mapper/
│   │   ├── __init__.py
│   │   └── device_mapper.py       # CCU3 channel -> HK accessory type; PV -> accessories
│   ├── hap/
│   │   ├── __init__.py
│   │   ├── bridge.py              # builds HAP bridge, registers accessories
│   │   └── accessories.py         # accessory factories (switch, light, cover, ...)
│   └── web/
│       ├── __init__.py
│       ├── api.py                 # FastAPI app + routes
│       └── static/                # index.html, app.js, styles.css, dashboard/table/solar
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── ccu3/test_client.py
    ├── ccu3/test_callback.py
    ├── ccu3/test_adapter.py
    ├── solaredge/test_adapter.py
    ├── mapper/test_device_mapper.py
    ├── hap/test_accessories.py
    └── web/test_api.py
```

**Decomposition rationale:** Each adapter is isolated behind a narrow interface so a failure in one source never crashes the others. The mapper is pure (no I/O) so it is trivially unit-testable. The HAP and web layers depend on the adapters/mapper through interfaces, not the reverse.

---

## Phase 0 — Scaffold & Tooling

### Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/homekit_bridge/__init__.py`, `tests/conftest.py`, `.gitignore`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "homekit-bridge"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "HAP-python>=4.9",
    "pymodbus>=3.6",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27", "ruff>=0.4"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Create empty `src/homekit_bridge/__init__.py` and `.gitignore`** (`.gitignore`: `__pycache__/`, `*.db`, `.env`, `state/`, `.superpowers/`)

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
```

- [ ] **Step 4: Verify env** — Run: `pip install -e ".[dev]" && pytest -q` → Expected: "no tests ran" (exit 0). Commit.

---

## Phase 1 — Core: models, settings, config, events

### Task 1: Domain models

**Files:** Create `src/homekit_bridge/models.py`; Test `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
from homekit_bridge.models import Channel, HKType, PVData

def test_channel_defaults():
    ch = Channel(address="ABC123:1", type="SWITCH", name="Lamp")
    assert ch.exported is False
    assert ch.hk_type is None

def test_pvdata_holds_values():
    pv = PVData(power_w=2450.0, energy_today_kwh=14.2, battery_pct=78, producing=True)
    assert pv.producing and pv.power_w == 2450.0
```

- [ ] **Step 2: Run → FAIL** (`pytest tests/test_models.py -v`)
- [ ] **Step 3: Implement `models.py`**

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class HKType(str, Enum):
    SWITCH = "switch"; OUTLET = "outlet"; LIGHTBULB = "lightbulb"
    COVER = "cover"; THERMOSTAT = "thermostat"; CONTACT = "contact"
    TEMPERATURE = "temperature"; HUMIDITY = "humidity"; MOTION = "motion"

@dataclass
class Channel:
    address: str            # CCU3 channel address, e.g. "OEQ0123456:1"
    type: str               # raw HM channel type, e.g. "SWITCH", "BLIND"
    name: str
    exported: bool = False
    hk_type: Optional[HKType] = None  # override; None => auto from `type`

@dataclass
class Device:
    address: str
    model: str
    channels: list[Channel] = field(default_factory=list)

@dataclass
class PVData:
    power_w: float = 0.0
    energy_today_kwh: float = 0.0
    battery_pct: Optional[int] = None
    producing: bool = False
    available: bool = True
```

- [ ] **Step 4: Run → PASS. Commit.**

### Task 2: Settings (env vars)

**Files:** Create `src/homekit_bridge/settings.py`; Test `tests/test_settings.py`

- [ ] **Step 1: Failing test** — set env vars via `monkeypatch`, assert `Settings.from_env()` reads `CCU3_HOST`, `SOLAREDGE_HOST`, `SOLAREDGE_UNIT_ID` (default 1), `WEB_PASSWORD` (default None), `STATE_DIR` (default `./state`).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `Settings` dataclass with `from_env()` classmethod using `os.environ.get`. Raise `ValueError` if `CCU3_HOST` or `SOLAREDGE_HOST` missing.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 3: Event bus

**Files:** Create `src/homekit_bridge/events.py`; Test `tests/test_events.py`

- [ ] **Step 1: Failing test**

```python
from homekit_bridge.events import EventBus

def test_subscribe_and_publish():
    bus = EventBus(); seen = []
    bus.subscribe("state", lambda e: seen.append(e))
    bus.publish("state", {"addr": "X:1", "value": True})
    assert seen == [{"addr": "X:1", "value": True}]

def test_handler_error_does_not_break_bus():
    bus = EventBus(); ok = []
    bus.subscribe("state", lambda e: (_ for _ in ()).throw(RuntimeError()))
    bus.subscribe("state", lambda e: ok.append(e))
    bus.publish("state", 1)  # must not raise
    assert ok == [1]
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** thread-safe `EventBus` (dict topic→list[callable], `threading.Lock`); `publish` calls handlers in try/except, logs exceptions, never propagates.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 4: Config store (SQLite)

**Files:** Create `src/homekit_bridge/config.py`; Test `tests/test_config.py`

- [ ] **Step 1: Failing test**

```python
from homekit_bridge.config import ConfigStore
from homekit_bridge.models import HKType

def test_upsert_and_get_channel(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.LIGHTBULB, name="Lamp")
    m = store.get_mapping("OEQ1:1")
    assert m["exported"] is True and m["hk_type"] == HKType.LIGHTBULB and m["name"] == "Lamp"

def test_list_exported(tmp_path):
    store = ConfigStore(tmp_path / "c.db")
    store.set_mapping("A:1", exported=True, hk_type=HKType.SWITCH, name="A")
    store.set_mapping("B:1", exported=False, hk_type=None, name="B")
    assert [m["address"] for m in store.list_exported()] == ["A:1"]
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `ConfigStore`: creates table `mappings(address PK, exported INT, hk_type TEXT, name TEXT)` on init; `set_mapping` does INSERT…ON CONFLICT UPDATE; `get_mapping`/`list_exported` return dicts; serialize `HKType` to its `.value`, deserialize back. Use a connection per call or a lock-guarded shared connection (`check_same_thread=False`).
- [ ] **Step 4: Run → PASS. Commit.**

---

## Phase 2 — CCU3 adapter

### Task 5: XML-RPC client wrapper

**Files:** Create `src/homekit_bridge/ccu3/client.py`; Test `tests/ccu3/test_client.py`

- [ ] **Step 1: Failing test** — inject a fake `xmlrpc` proxy (duck-typed object) into `Ccu3Client`. Assert:
  - `set_value("OEQ1:1", "STATE", True)` calls proxy `setValue("OEQ1:1", "STATE", True)`.
  - `get_value("OEQ1:1", "STATE")` returns proxy result.
  - `list_devices()` maps proxy `listDevices()` output (list of dicts with `ADDRESS`, `TYPE`, `PARENT`/`CHILDREN`) into `Device`/`Channel` objects.

```python
from homekit_bridge.ccu3.client import Ccu3Client

class FakeProxy:
    def __init__(self): self.calls = []
    def setValue(self, a, k, v): self.calls.append(("set", a, k, v))
    def getValue(self, a, k): return "ON"
    def listDevices(self):
        return [
            {"ADDRESS": "OEQ1", "TYPE": "HM-LC-Sw1", "CHILDREN": ["OEQ1:1"]},
            {"ADDRESS": "OEQ1:1", "TYPE": "SWITCH", "PARENT": "OEQ1"},
        ]

def test_set_and_get():
    p = FakeProxy(); c = Ccu3Client(proxy=p)
    c.set_value("OEQ1:1", "STATE", True)
    assert p.calls == [("set", "OEQ1:1", "STATE", True)]
    assert c.get_value("OEQ1:1", "STATE") == "ON"

def test_list_devices_builds_channels():
    c = Ccu3Client(proxy=FakeProxy())
    devices = c.list_devices()
    chans = [ch for d in devices for ch in d.channels]
    assert any(ch.address == "OEQ1:1" and ch.type == "SWITCH" for ch in chans)
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `Ccu3Client(host=None, port=2001, proxy=None)`: if `proxy` is None build `xmlrpc.client.ServerProxy(f"http://{host}:{port}")`. Methods `set_value`, `get_value`, `list_devices` (group channels under parent devices). Catch `Exception` and re-raise as `Ccu3Error`.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 6: XML-RPC callback server

**Files:** Create `src/homekit_bridge/ccu3/callback.py`; Test `tests/ccu3/test_callback.py`

- [ ] **Step 1: Failing test** — start `CallbackServer(on_event=cb)` on port 0, retrieve bound port, send an XML-RPC `event(interface_id, address, key, value)` call via `xmlrpc.client.ServerProxy`, assert `cb` received `(address, key, value)`. Also assert it answers the CCU3 `system.listMethods`/`event`/`listDevices`/`newDevices` housekeeping calls without error (return empty list / "").
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `CallbackServer` using `xmlrpc.server.SimpleXMLRPCServer` in a background thread. Register `event`, `listDevices` (→ []), `newDevices` (→ ""), `deleteDevices` (→ ""), `updateDevice` (→ ""), `system.multicall`. `event` invokes `on_event(address, key, value)`. Expose `.url` and `.start()/.stop()`.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 7: CCU3 adapter (orchestration + reconnect)

**Files:** Create `src/homekit_bridge/ccu3/adapter.py`; Test `tests/ccu3/test_adapter.py`

- [ ] **Step 1: Failing test** — with a fake client + fake callback, assert:
  - `start()` calls client `init(callback_url, interface_id)` to register the callback.
  - An incoming callback event is published to the EventBus on topic `"ccu3.state"` as `{"address","key","value"}`.
  - `set_value` delegates to the client.
  - On client `init` raising, adapter retries with backoff (assert it schedules a retry; use an injected sleep/clock to avoid real waits).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `Ccu3Adapter(client, callback_server, bus, interface_id="homekit-bridge", sleep=time.sleep)`. `start()` starts callback server, calls `client.init(callback_url, interface_id)`, wires `callback.on_event` → bus.publish. Reconnect loop with capped exponential backoff. `re_register()` re-inits after CCU3 restart (detected via repeated event timeout or explicit health check).
- [ ] **Step 4: Run → PASS. Commit.**

---

## Phase 3 — SolarEdge adapter

### Task 8: Register map + adapter

**Files:** Create `src/homekit_bridge/solaredge/registers.py`, `adapter.py`; Test `tests/solaredge/test_adapter.py`

- [ ] **Step 1: Failing test** — inject a fake Modbus client whose `read_holding_registers` returns canned raw register words; assert `SolarEdgeAdapter.read()` returns a `PVData` with decoded `power_w`, `battery_pct`, `producing` (power>10W). Assert on read exception `read()` returns `PVData(available=False)` and does not raise.

```python
from homekit_bridge.solaredge.adapter import SolarEdgeAdapter

class FakeModbus:
    def __init__(self, raise_=False): self.raise_ = raise_
    def read_holding_registers(self, addr, count, slave=1):
        if self.raise_: raise OSError("timeout")
        return FakeResp()  # provide .registers with scale+value words

def test_read_decodes_power():
    a = SolarEdgeAdapter(client=FakeModbus())
    pv = a.read()
    assert pv.available and pv.power_w >= 0

def test_read_handles_timeout():
    a = SolarEdgeAdapter(client=FakeModbus(raise_=True))
    assert a.read().available is False
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `registers.py` with SunSpec register constants (AC power 40083/40084 scale, battery SoC). `SolarEdgeAdapter(host=None, unit_id=1, client=None)` builds `pymodbus.client.ModbusTcpClient(host, port=1502)` if no client. `read()` reads registers, applies SunSpec scale factor, builds `PVData`; wraps all errors → `available=False`. Add `poll(bus, interval=5, stop_event=...)` loop publishing `"solaredge.data"`.
- [ ] **Step 4: Run → PASS. Commit.**

> **Plan note for implementer:** Exact registers depend on inverter model/firmware; verify against the live inverter on first connect and adjust `registers.py`. Tests use injected fakes so they remain valid regardless.

---

## Phase 4 — Device mapper (pure)

### Task 9: CCU3 channel → HomeKit type

**Files:** Create `src/homekit_bridge/mapper/device_mapper.py`; Test `tests/mapper/test_device_mapper.py`

- [ ] **Step 1: Failing test**

```python
from homekit_bridge.mapper.device_mapper import auto_hk_type
from homekit_bridge.models import HKType

import pytest
@pytest.mark.parametrize("hm,expected", [
    ("SWITCH", HKType.SWITCH),
    ("DIMMER", HKType.LIGHTBULB),
    ("BLIND", HKType.COVER),
    ("SHUTTER_CONTACT", HKType.CONTACT),
    ("CLIMATECONTROL_RT_TRANSCEIVER", HKType.THERMOSTAT),
    ("MOTIONDETECTOR", HKType.MOTION),
    ("WEATHER", HKType.TEMPERATURE),
    ("UNKNOWN_FOO", None),
])
def test_auto_hk_type(hm, expected):
    assert auto_hk_type(hm) == expected
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `auto_hk_type(hm_type: str) -> Optional[HKType]` with a substring/prefix rule table covering the v1 mapping (Switch/Outlet, Dimmer→Lightbulb, Blind/Shutter→Cover, eTRV/Climate→Thermostat, contact, temp/humidity, motion). Unknown → None. Also `resolve_hk_type(channel, mapping)` that prefers explicit override from config, else `auto_hk_type`.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 10: PV → accessory definitions

**Files:** Modify `device_mapper.py`; Test same file

- [ ] **Step 1: Failing test** — `pv_accessory_specs(PVData(power_w=2450, battery_pct=78, producing=True))` returns specs for: a light-sensor accessory with `lux == 2450`, an Eve-power custom accessory (`watts == 2450`, `kwh`), a battery service (`78`), and a contact/switch "producing" accessory (`on == True`). Assert structure (list of dicts with `kind` and value fields).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `pv_accessory_specs(pv) -> list[dict]` returning the four spec dicts (variant C). Pure function, no HAP imports.
- [ ] **Step 4: Run → PASS. Commit.**

---

## Phase 5 — HAP bridge

### Task 11: Accessory factories

**Files:** Create `src/homekit_bridge/hap/accessories.py`; Test `tests/hap/test_accessories.py`

- [ ] **Step 1: Failing test** — using HAP-python's `AccessoryDriver` in a test (no network: `driver = AccessoryDriver(port=0, persist_file=str(tmp_path/'a.state'))`), build a `SwitchAccessory(driver, "Lamp", on_set=cb)`; simulate a HomeKit SET on the On characteristic → assert `cb(True)` called. Build a `CoverAccessory` and assert setting target position triggers callback with 0–100.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** factory classes subclassing `pyhap.accessory.Accessory` for: Switch, Outlet, Lightbulb(+Brightness), WindowCovering, Thermostat, ContactSensor, TemperatureSensor, HumiditySensor, MotionSensor, plus PV: LightSensor (lux), Eve power (custom UUID characteristics), BatteryService, "producing" ContactSensor. Each takes `on_set`/`on_get` callbacks. Provide `update_state(...)` methods to push values from events.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 12: Bridge wiring

**Files:** Create `src/homekit_bridge/hap/bridge.py`; Test `tests/hap/test_bridge.py`

- [ ] **Step 1: Failing test** — `HomeKitBridge(driver, config_store, ccu3_adapter, bus)`; given config with two exported channels, `build()` adds two accessories to the bridge. Publishing a `"ccu3.state"` event for an exported address calls the matching accessory's `update_state`. A HomeKit SET on a switch calls `ccu3_adapter.set_value(address, key, value)`.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `HomeKitBridge`: builds `pyhap.accessory.Bridge`, iterates `config_store.list_exported()`, resolves HK type via mapper, instantiates accessory with `on_set` → `ccu3_adapter.set_value`, registers an address→accessory index. Subscribes to `"ccu3.state"` and `"solaredge.data"` on the bus to push updates. Single bridge = single pairing.
- [ ] **Step 4: Run → PASS. Commit.**

---

## Phase 6 — Web API

### Task 13: FastAPI routes

**Files:** Create `src/homekit_bridge/web/api.py`; Test `tests/web/test_api.py`

- [ ] **Step 1: Failing test** (httpx `TestClient`, inject fake ccu3 adapter + real ConfigStore in tmp):
  - `GET /api/devices` → list of discovered channels with current export/hk_type/name.
  - `POST /api/devices/{address}` body `{exported, hk_type, name}` → persists to ConfigStore; returns 200.
  - `GET /api/solar` → latest PVData JSON.
  - `GET /api/status` → bridge paired state, counts, source connectivity.
  - `GET /health` → `{"status":"ok"}`.
  - With `WEB_PASSWORD` set, requests without correct `Authorization` → 401.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `create_app(config_store, ccu3_adapter, solar_state, settings)` returning FastAPI app with the routes above, optional HTTP Basic auth dependency when `settings.web_password`, and `StaticFiles` mount at `/` serving `web/static`.
- [ ] **Step 4: Run → PASS. Commit.**

---

## Phase 7 — Frontend (Vanilla JS, Hybrid layout)

> Frontend tasks are validated by: served by FastAPI, no build step, no framework, works against the real `/api/*` endpoints. Manual acceptance via browser; logic units (formatting, fetch wrappers) get small JS unit checks run with `node --test` where practical, otherwise smoke-tested through the API test.

### Task 14: Static shell + dashboard

**Files:** Create `src/homekit_bridge/web/static/index.html`, `styles.css`, `app.js`

- [ ] **Step 1:** Build the app shell with two views (Dashboard + Geräte) and a Solar panel, matching the approved Hybrid layout (dashboard tiles on start, table for management). Use `fetch('/api/...')`. No framework, no bundler.
- [ ] **Step 2:** Dashboard renders status tiles from `/api/status` + `/api/solar` (active devices, PV power, producing state) with auto-refresh (poll every 5 s).
- [ ] **Step 3:** Commit.

### Task 15: Device table (select / map / rename)

**Files:** Modify `app.js`, `index.html`, `styles.css`

- [ ] **Step 1:** Table from `/api/devices`: search box, per-row "Export"-toggle, HomeKit-type dropdown (HKType values), editable name; "Save" → `POST /api/devices/{address}`.
- [ ] **Step 2:** Optimistic UI + error toast on failed save.
- [ ] **Step 3:** Commit.

### Task 16: Solar view

**Files:** Modify `app.js`, `index.html`

- [ ] **Step 1:** Solar panel: live power (W), today's kWh, battery %, producing badge from `/api/solar`, polling every 5 s; simple inline bar for current vs. peak.
- [ ] **Step 2:** Commit.

---

## Phase 8 — Integration, packaging, docs

### Task 17: Entrypoint wiring

**Files:** Create `src/homekit_bridge/__main__.py`; Test `tests/test_main_wiring.py` (smoke: `build_app()` constructs all components with fakes and returns without starting network servers)

- [ ] **Step 1: Failing test** — `from homekit_bridge.__main__ import build` builds settings (from env via monkeypatch), ConfigStore (tmp), adapters (with injected fakes), bridge, FastAPI app; returns an object exposing `.app` and `.start()/.stop()` without binding real ports.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `build(settings, *, fakes=None)` factory + `main()` that: loads settings, creates `AccessoryDriver` (HAP) on configured port + persist file under `STATE_DIR`, starts CCU3 adapter, starts SolarEdge poll thread, builds bridge, runs Uvicorn for the web app, prints/loggs the HomeKit pairing QR/PIN. Graceful shutdown on SIGTERM.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 18: Docker + compose + env example

**Files:** Create `Dockerfile`, `docker-compose.yml`, `.env.example`

- [ ] **Step 1:** `Dockerfile`: python:3.12-slim, install package, expose nothing special, CMD `python -m homekit_bridge`.
- [ ] **Step 2:** `docker-compose.yml`: `network_mode: host` (required for HAP mDNS), volume `./state:/app/state`, env from `.env`.
- [ ] **Step 3:** `.env.example` with `CCU3_HOST=`, `SOLAREDGE_HOST=`, `SOLAREDGE_UNIT_ID=1`, `WEB_PASSWORD=`, `STATE_DIR=/app/state`.
- [ ] **Step 4:** `docker build .` succeeds. Commit.

### Task 19: README + final review

**Files:** Create `README.md`

- [ ] **Step 1:** Document: what it is, requirements (CCU3 XML-RPC reachable, SolarEdge Modbus enabled on port 1502), setup (`.env`, `docker compose up`), HomeKit pairing (scan QR / PIN from logs), host-network requirement, adding/mapping devices in the web UI, troubleshooting (callback re-registration after CCU3 restart).
- [ ] **Step 2:** Run full suite `pytest -q` → all green; `ruff check`. Commit.

---

## Self-Review (against spec)

- **CCU3 read+switch, real-time:** Tasks 5–7, 11–12. ✓
- **SolarEdge Modbus read-only live:** Task 8. ✓
- **Variant C PV representation:** Tasks 10, 11. ✓
- **Web UI Hybrid (dashboard + table + solar):** Tasks 13–16. ✓
- **SQLite mappings, env secrets:** Tasks 2, 4, 13. ✓
- **Single bridge / one pairing, host network, persisted state:** Tasks 12, 17, 18. ✓
- **Error handling / isolation / reconnect / /health:** Tasks 7, 8, 13, 17. ✓
- **Tests with mocked CCU3/Modbus, happy + error paths:** every adapter/mapper task. ✓
- **Type consistency:** `HKType`, `Channel`, `PVData`, `set_value`, `list_exported`, `auto_hk_type`, `pv_accessory_specs` used consistently across tasks. ✓

No placeholders remain; the two "verify against live hardware" notes (SolarEdge registers, exact HM parameter keys) are intentional runtime-verification items, isolated behind injected fakes so tests are deterministic.
```
