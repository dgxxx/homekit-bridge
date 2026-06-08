# Live-Accessory-Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In der Web-UI exportierte CCU3-Geräte erscheinen sofort (ohne Neustart) in Apple HomeKit, und der Build crasht nicht mehr an read-only Sensoren.

**Architecture:** Bug-B-Fix in `make_accessory` (übergibt `on_set` nur an Klassen, die es akzeptieren). `HomeKitBridge` bekommt einen `reconcile()`, der die SQLite-Exporte gegen den laufenden Accessory-Bestand abgleicht und den HAP-Eingriff via `driver.loop.call_soon_threadsafe` race-frei auf den Driver-Loop marshallt. Der Web-POST publisht `config.changed` auf den bestehenden In-Process-Eventbus; die Bridge abonniert es.

**Tech Stack:** Python 3.12, pyhap (HAP-python), FastAPI, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-live-accessory-reconcile-design.md`

**Arbeitsverzeichnis:** alle Pfade relativ zu `homekit-bridge/`. Tests: `pytest -q` aus `homekit-bridge/`. Vor jedem Commit `ruff check --fix src tests` (Definition of Done). Branch `feat/live-accessory-reconcile` ist bereits aktiv. Commit-Trailer anhängen: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Bug-B-Fix (`make_accessory`) + Build-Schleife absichern

**Files:**
- Modify: `src/homekit_bridge/hap/accessories.py` (`make_accessory`)
- Modify: `src/homekit_bridge/hap/bridge.py` (`_build_ccu3_accessories` try/except)
- Test: `tests/hap/test_accessories.py`, `tests/hap/test_bridge.py`

- [ ] **Step 1: Failing tests für make_accessory**

In `tests/hap/test_accessories.py` die Import-Zeile ergänzen (Funktion `make_accessory`):

```python
from homekit_bridge.hap.accessories import (
    make_accessory,
    SwitchAccessory,
    OutletAccessory,
    LightbulbAccessory,
    CoverAccessory,
    ThermostatAccessory,
    ContactSensorAccessory,
    TemperatureSensorAccessory,
    HumiditySensorAccessory,
    MotionSensorAccessory,
    # PV accessories
    LightSensorAccessory,
    EvePowerAccessory,
    BatteryAccessory,
    ProducingAccessory,
)
```

Am Dateiende anfügen:

```python
# ---------------------------------------------------------------------------
# make_accessory factory — on_set handling
# ---------------------------------------------------------------------------

def test_make_accessory_sensor_ignores_on_set(driver):
    # Read-only sensors don't accept on_set; passing it must NOT raise.
    acc = make_accessory(driver=driver, hk_type="contact", name="Door", on_set=lambda v: None)
    assert isinstance(acc, ContactSensorAccessory)


def test_make_accessory_switch_wires_on_set(driver):
    received = []
    acc = make_accessory(
        driver=driver, hk_type="switch", name="Lamp", on_set=lambda v: received.append(v)
    )
    assert isinstance(acc, SwitchAccessory)
    char = acc.get_service("Switch").get_characteristic("On")
    char.client_update_value(True)
    assert received == [True]


def test_make_accessory_unknown_type_returns_none(driver):
    assert make_accessory(driver=driver, hk_type="nonsense", name="x") is None
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/hap/test_accessories.py::test_make_accessory_sensor_ignores_on_set -q`
Expected: FAIL — `TypeError: ContactSensorAccessory.__init__() got an unexpected keyword argument 'on_set'`.

- [ ] **Step 3: make_accessory fixen**

In `src/homekit_bridge/hap/accessories.py` das Modul-Import um `inspect` ergänzen (oberste Importzeile):

```python
import inspect
import logging
from typing import Any, Callable, Optional
```

Und `make_accessory` ersetzen durch:

```python
def make_accessory(
    driver: AccessoryDriver,
    hk_type: str,
    name: str,
    on_set: Optional[Callable] = None,
) -> Optional[Accessory]:
    """Instantiate the correct accessory class for *hk_type*.

    ``on_set`` is only forwarded to accessory classes whose constructor accepts
    it; read-only sensors (contact/temperature/humidity/motion) ignore it
    instead of raising.  Returns ``None`` for unknown types so callers can skip
    gracefully.
    """
    cls = _FACTORY_MAP.get(hk_type)
    if cls is None:
        logger.warning("Unknown HKType '%s' for accessory '%s'", hk_type, name)
        return None
    kwargs: dict[str, Any] = {"driver": driver, "name": name}
    if on_set is not None and "on_set" in inspect.signature(cls.__init__).parameters:
        kwargs["on_set"] = on_set
    return cls(**kwargs)
```

- [ ] **Step 4: make_accessory-Tests grün**

Run: `pytest tests/hap/test_accessories.py -q`
Expected: PASS (alle, inkl. der drei neuen).

- [ ] **Step 5: Failing test für crash-sicheren Build (contact export)**

In `tests/hap/test_bridge.py` am Dateiende anfügen:

```python
def test_build_with_contact_export_registers_accessory(driver, store, bus, ccu3):
    store.set_mapping("0000DD898F35C7:1", exported=True, hk_type=HKType.CONTACT,
                      name="Tür Arbeitszimmer")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()  # must not raise (Bug B)
    assert len(bridge.accessories) == 1
    acc = bridge.accessories[0]
    assert acc.get_service("ContactSensor") is not None
```

- [ ] **Step 6: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/hap/test_bridge.py::test_build_with_contact_export_registers_accessory -q`
Expected: PASS already if Step 3 done — but to confirm Bug B is the gate, this test passes only because Step 3 fixed make_accessory. (If run before Step 3 it would FAIL with TypeError.) Proceed.

- [ ] **Step 7: Build-Schleife absichern (Defense-in-Depth)**

In `src/homekit_bridge/hap/bridge.py`, `_build_ccu3_accessories` — den Accessory-Bau pro Mapping in try/except kapseln. Ersetze den Block ab `acc = make_accessory(` bis `self._addr_index[address] = acc`:

```python
            try:
                acc = make_accessory(
                    driver=self._driver,
                    hk_type=hk_type.value,
                    name=name,
                    on_set=_make_setter(address),
                )
            except Exception:
                logger.exception("Failed to build accessory for %s", address)
                continue
            if acc is None:
                continue

            self.hap_bridge.add_accessory(acc)
            self._addr_index[address] = acc
```

- [ ] **Step 8: Volle Suite grün + Lint**

Run: `ruff check --fix src tests && pytest -q`
Expected: PASS (104+ Tests grün, ruff sauber).

- [ ] **Step 9: Commit**

```bash
git add src/homekit_bridge/hap/accessories.py src/homekit_bridge/hap/bridge.py tests/hap/test_accessories.py tests/hap/test_bridge.py
git commit -m "fix: make_accessory ignores on_set for read-only sensors; guard build loop"
```

---

### Task 2: Reconcile in HomeKitBridge (Helper, Indizes, reconcile/_apply, Subscription)

**Files:**
- Modify: `src/homekit_bridge/hap/bridge.py`
- Test: `tests/hap/test_bridge.py`

- [ ] **Step 1: Failing tests für reconcile**

In `tests/hap/test_bridge.py` am Dateiende anfügen. Diese Tests führen den auf den Driver-Loop marshallten Pfad synchron aus, indem `driver.loop.call_soon_threadsafe` gepatcht wird, und spionieren `driver.config_changed`:

```python
def _sync_reconcile(bridge, driver, monkeypatch):
    """Make reconcile() apply synchronously and count config_changed calls."""
    calls = {"config_changed": 0}
    monkeypatch.setattr(driver.loop, "call_soon_threadsafe",
                        lambda fn, *a: fn(*a))
    monkeypatch.setattr(driver, "config_changed",
                        lambda: calls.__setitem__("config_changed",
                                                  calls["config_changed"] + 1))
    return calls


def test_reconcile_adds_newly_exported_accessory(driver, store, bus, ccu3, monkeypatch):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    assert len(bridge.accessories) == 0

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge.reconcile()

    assert len(bridge.accessories) == 1
    assert calls["config_changed"] == 1


def test_reconcile_removes_unexported_accessory(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    assert len(bridge.accessories) == 1

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=False, hk_type=HKType.SWITCH, name="Lamp")
    bridge.reconcile()

    assert len(bridge.accessories) == 0
    assert calls["config_changed"] == 1


def test_reconcile_replaces_on_hk_type_change(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Dev")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first = bridge.accessories[0]

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.OUTLET, name="Dev")
    bridge.reconcile()

    assert len(bridge.accessories) == 1
    new = bridge.accessories[0]
    assert new is not first
    assert new.get_service("Outlet") is not None
    assert calls["config_changed"] == 1


def test_reconcile_name_only_change_is_noop(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Old")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    first = bridge.accessories[0]

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="New")
    bridge.reconcile()

    # Same accessory object, no replace, no config_changed (AID/room preserved).
    assert bridge.accessories[0] is first
    assert calls["config_changed"] == 0


def test_reconcile_no_change_does_not_call_config_changed(driver, store, bus, ccu3, monkeypatch):
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    bridge.reconcile()  # nothing changed in the store

    assert calls["config_changed"] == 0


def test_config_changed_event_triggers_reconcile(driver, store, bus, ccu3, monkeypatch):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()

    calls = _sync_reconcile(bridge, driver, monkeypatch)
    store.set_mapping("OEQ1:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bus.publish("config.changed", {"address": "OEQ1:1"})

    assert len(bridge.accessories) == 1
    assert calls["config_changed"] == 1
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/hap/test_bridge.py::test_reconcile_adds_newly_exported_accessory -q`
Expected: FAIL — `AttributeError: 'HomeKitBridge' object has no attribute 'reconcile'`.

- [ ] **Step 3: bridge.py refactoren + reconcile/_apply implementieren**

In `src/homekit_bridge/hap/bridge.py`:

(a) Im `__init__` nach `self._addr_index: dict[str, Accessory] = {}` ergänzen:

```python
        # address -> the exported mapping used to build the accessory (change detection)
        self._exported: dict[str, dict] = {}
```

(b) Eine `_make_setter`-Methode und einen `_make_ccu3_accessory`-Helper hinzufügen (z.B. direkt vor `_build_ccu3_accessories`):

```python
    def _make_setter(self, addr: str) -> Any:
        def on_set(value: Any) -> None:
            try:
                self._ccu3.set_value(addr, "STATE", value)
            except Exception:
                logger.exception("set_value failed for %s", addr)
        return on_set

    def _make_ccu3_accessory(self, mapping: dict) -> Optional[Accessory]:
        address = mapping["address"]
        name = mapping["name"] or address
        hk_type = resolve_hk_type(_ChannelProxy(address=address, hm_type=""), mapping)
        if hk_type is None:
            logger.info("Skipping %s: no HKType resolved", address)
            return None
        return make_accessory(
            driver=self._driver,
            hk_type=hk_type.value,
            name=name,
            on_set=self._make_setter(address),
        )
```

(c) `_build_ccu3_accessories` ersetzen, sodass es den Helper nutzt, `_exported` füllt und crash-sicher bleibt:

```python
    def _build_ccu3_accessories(self) -> None:
        for mapping in self._store.list_exported():
            address: str = mapping["address"]
            try:
                acc = self._make_ccu3_accessory(mapping)
            except Exception:
                logger.exception("Failed to build accessory for %s", address)
                continue
            if acc is None:
                continue
            self.hap_bridge.add_accessory(acc)
            self._addr_index[address] = acc
            self._exported[address] = mapping
```

(d) In `build()` nach den beiden bestehenden `self._bus.subscribe(...)`-Zeilen ergänzen:

```python
        self._bus.subscribe("config.changed", self.reconcile)
```

(e) `reconcile` und `_apply` als neue Methoden hinzufügen (z.B. nach `_build_pv_accessories`):

```python
    def reconcile(self, _event: Any = None) -> None:
        """Diff exported mappings against live accessories; apply on the driver loop.

        Reacts to export (add), un-export (remove) and hk_type change (replace).
        Name-only changes are intentionally ignored so HomeKit's per-AID room/name
        assignment is preserved (see design doc).
        """
        desired = {m["address"]: m for m in self._store.list_exported()}
        to_add: list[dict] = []
        to_remove: list[str] = []
        for addr, m in desired.items():
            cur = self._exported.get(addr)
            if cur is None:
                to_add.append(m)
            elif cur.get("hk_type") != m.get("hk_type"):
                to_remove.append(addr)
                to_add.append(m)
        for addr in self._exported:
            if addr not in desired:
                to_remove.append(addr)
        if not to_add and not to_remove:
            return
        self._driver.loop.call_soon_threadsafe(self._apply, to_add, to_remove)

    def _apply(self, to_add: list[dict], to_remove: list[str]) -> None:
        """Mutate the HAP bridge.  Runs on the driver event loop (race-free)."""
        changed = False
        for addr in to_remove:
            acc = self._addr_index.pop(addr, None)
            self._exported.pop(addr, None)
            if acc is not None and acc.aid in self.hap_bridge.accessories:
                del self.hap_bridge.accessories[acc.aid]
                changed = True
        for mapping in to_add:
            address = mapping["address"]
            try:
                acc = self._make_ccu3_accessory(mapping)
            except Exception:
                logger.exception("Failed to build accessory for %s", address)
                continue
            if acc is None:
                continue
            self.hap_bridge.add_accessory(acc)
            self._addr_index[address] = acc
            self._exported[address] = mapping
            changed = True
        if changed:
            self._driver.config_changed()
```

(f) Sicherstellen, dass die Importe `make_accessory` und `resolve_hk_type` vorhanden sind (sie sind bereits importiert).

- [ ] **Step 4: Reconcile-Tests grün**

Run: `pytest tests/hap/test_bridge.py -q`
Expected: PASS (alle bestehenden + 6 neue).

- [ ] **Step 5: Volle Suite grün + Lint**

Run: `ruff check --fix src tests && pytest -q`
Expected: PASS, ruff sauber.

- [ ] **Step 6: Commit**

```bash
git add src/homekit_bridge/hap/bridge.py tests/hap/test_bridge.py
git commit -m "feat: live reconcile of exported accessories via config.changed event"
```

---

### Task 3: Web-Wiring — config.changed publizieren + bus durchreichen

**Files:**
- Modify: `src/homekit_bridge/web/api.py` (`create_app` Signatur + POST publisht Event)
- Modify: `src/homekit_bridge/__main__.py` (`bus` an `create_app`)
- Test: `tests/web/test_api.py`, `tests/test_main_wiring.py`

- [ ] **Step 1: Failing test — POST publisht config.changed**

In `tests/web/test_api.py`:

(a) Import ergänzen (oben bei den Imports):

```python
from homekit_bridge.events import EventBus
```

(b) Eine `bus`-Fixture hinzufügen (nahe den anderen Fixtures, z.B. nach der `bridge_state`-Fixture):

```python
@pytest.fixture
def bus():
    return EventBus()
```

(c) Die Fixtures `app` und `auth_app` um `bus` erweitern:

```python
@pytest.fixture
def app(store, ccu3, solar, bridge_state, bus):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
        bus=bus,
    )


@pytest.fixture
def auth_app(store, ccu3, solar, bridge_state, bus):
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(web_password="secret"),
        bus=bus,
    )
```

(d) Neuen Test am Dateiende anfügen:

```python
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
```

- [ ] **Step 2: Die zwei inline `create_app(...)`-Aufrufe in test_api.py um `bus` erweitern**

In `tests/web/test_api.py` gibt es zwei weitere `create_app(...)`-Aufrufe (in den Discovery-Fixtures, ~Zeile 254 und ~Zeile 331). Beide bekommen den Parameter `bus=EventBus()`. Beispiel — den Aufruf

```python
    return create_app(
        config_store=store,
        ccu3_adapter=ccu3,
        solar_state=solar,
        bridge_state=bridge_state,
        settings=_make_settings(),
    )
```

ersetzen durch denselben Aufruf mit zusätzlicher letzter Zeile `        bus=EventBus(),` vor der schließenden Klammer. (Gilt für beide Vorkommen; der zweite hat ggf. einen `ccu3`/`failing`-Adapter — nur die `bus=`-Zeile ergänzen, sonst nichts ändern.)

- [ ] **Step 3: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/web/test_api.py::test_post_device_publishes_config_changed -q`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'bus'`.

- [ ] **Step 4: create_app implementieren**

In `src/homekit_bridge/web/api.py`:

(a) Import ergänzen (bei den `homekit_bridge`-Importen):

```python
from homekit_bridge.events import EventBus
```

(b) Signatur von `create_app` um `bus` erweitern:

```python
def create_app(
    config_store: ConfigStore,
    ccu3_adapter: Any,
    solar_state: Any,
    bridge_state: Any,
    settings: Settings,
    bus: EventBus,
) -> FastAPI:
```

(c) Im `post_device`-Handler nach `config_store.set_mapping(...)` das Event publizieren:

```python
        config_store.set_mapping(
            address,
            exported=body.exported,
            hk_type=hk_type,
            name=body.name,
        )
        bus.publish("config.changed", {"address": address})
        return {"status": "ok", "address": address}
```

- [ ] **Step 5: Failing test für __main__-Wiring**

In `tests/test_main_wiring.py` am Dateiende anfügen:

```python
def test_create_app_receives_bus(tmp_path, monkeypatch):
    """build() must pass the EventBus into create_app so POSTs can publish."""
    import homekit_bridge.__main__ as m
    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(m, "create_app", fake_create_app)
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    m.build(fakes={"mqtt_client": FakeMqttClient()})

    assert "bus" in captured
    assert captured["bus"] is not None
```

`FakeMqttClient` ist bereits oben in `tests/test_main_wiring.py` definiert (genutzt von den bestehenden `build(fakes={"mqtt_client": FakeMqttClient()})`-Tests) — keine neue Klasse nötig.

- [ ] **Step 6: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_main_wiring.py::test_create_app_receives_bus -q`
Expected: FAIL — `KeyError: 'bus'` bzw. AssertionError (bus nicht übergeben).

- [ ] **Step 7: __main__ verdrahten**

In `src/homekit_bridge/__main__.py` den `create_app(...)`-Aufruf in `build()` um `bus=bus` erweitern:

```python
    app = create_app(
        config_store=config_store,
        ccu3_adapter=ccu3_adapter,
        solar_state=solar_state,
        bridge_state=bridge_state,
        settings=settings,
        bus=bus,
    )
```

- [ ] **Step 8: Volle Suite grün + Lint**

Run: `ruff check --fix src tests && pytest -q`
Expected: PASS (alle Tests grün, inkl. der angepassten Fixtures), ruff sauber.

- [ ] **Step 9: Commit**

```bash
git add src/homekit_bridge/web/api.py src/homekit_bridge/__main__.py tests/web/test_api.py tests/test_main_wiring.py
git commit -m "feat: web POST publishes config.changed; wire bus into create_app"
```

---

## Self-Review-Ergebnis

- **Spec-Abdeckung:** Bug-B-Fix `make_accessory` (T1), Build-Schleife absichern (T1), Helper `_make_ccu3_accessory` + `_make_setter`-Methode (T2), `_exported`-Index (T2), `reconcile`/`_apply` + `call_soon_threadsafe`-Marshalling (T2), `config.changed`-Subscription (T2), name-only → kein Replace (T2 Test), Web-`bus`-Param + Event-Publish (T3), `__main__`-Wiring (T3). Tests für alle Reconcile-Fälle inkl. no-op und Event-getrieben.
- **Platzhalter:** keine (Step 5/T3 verweist auf den in der Datei bereits existierenden MQTT-Fake — bewusst, um den genauen vorhandenen Ausdruck wiederzuverwenden statt einen falschen zu erfinden).
- **Typ-Konsistenz:** `reconcile(self, _event=None)`, `_apply(self, to_add, to_remove)`, `_make_ccu3_accessory(self, mapping)`, `_make_setter(self, addr)`, `self._exported`, `self._addr_index` durchgängig identisch verwendet; `make_accessory(driver, hk_type, name, on_set)`-Signatur in T1 und T2 gleich; `create_app(..., bus)` in T3 in api.py, __main__ und Tests konsistent.
