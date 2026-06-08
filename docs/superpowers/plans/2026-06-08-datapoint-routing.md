# Datenpunkt-bewusstes State-Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HomeKit zeigt für ein Thermostat Ist-Temperatur, Soll-Temperatur und Feuchte korrekt an und kann die Soll-Temperatur setzen — durch datenpunkt-bewusstes Routing (HM-Datenpunkt ↔ HomeKit-Charakteristik) statt blindem „letzter Wert gewinnt".

**Architecture:** Eine zentrale reine Tabelle (`mapper/datapoints.py`) übersetzt HM-Datenpunkte ↔ HomeKit-Charakteristiken in beide Richtungen. Die Bridge routet eingehende `ccu3.state`-Events darüber auf `accessory.update_state(**kwargs)` und verdrahtet beschreibbare Charakteristiken über `accessory.writable_characteristics()` + die Schreib-Tabelle. Accessories werden reine HAP-Anzeigeobjekte.

**Tech Stack:** Python 3.12, pyhap (HAP-python), pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-datapoint-routing-design.md`

**Arbeitsverzeichnis:** alle Pfade relativ zu `homekit-bridge/`. Tests: `pytest -q`. Vor jedem Commit `ruff check --fix src tests`. Branch `feat/datapoint-routing` ist aktiv. Commit-Trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: `mapper/datapoints.py` — reine Mapping-Tabelle

**Files:**
- Create: `src/homekit_bridge/mapper/datapoints.py`
- Create: `tests/mapper/test_datapoints.py`

- [ ] **Step 1: Failing tests**

Create `tests/mapper/test_datapoints.py`:
```python
from homekit_bridge.mapper.datapoints import read_update, WRITE_DATAPOINTS
from homekit_bridge.models import HKType


def test_thermostat_read_datapoints():
    assert read_update(HKType.THERMOSTAT, "ACTUAL_TEMPERATURE", 25.0) == {"current_temp": 25.0}
    assert read_update(HKType.THERMOSTAT, "SET_POINT_TEMPERATURE", 4.5) == {"target_temp": 4.5}
    assert read_update(HKType.THERMOSTAT, "HUMIDITY", 40) == {"humidity": 40}


def test_thermostat_ignores_unknown_datapoints():
    assert read_update(HKType.THERMOSTAT, "BOOST_MODE", False) is None
    assert read_update(HKType.THERMOSTAT, "PARTY_MODE", False) is None


def test_switch_and_contact_read():
    assert read_update(HKType.SWITCH, "STATE", True) == {"on": True}
    assert read_update(HKType.CONTACT, "STATE", False) == {"contact_detected": False}


def test_cover_level_is_scaled_to_percent():
    assert read_update(HKType.COVER, "LEVEL", 0.5) == {"position": 50.0}


def test_unknown_type_returns_none():
    assert read_update(HKType.MOTION, "NONSENSE", 1) is None


def test_write_datapoints_table():
    assert WRITE_DATAPOINTS[HKType.THERMOSTAT]["target_temp"].kwarg == "SET_POINT_TEMPERATURE"
    assert WRITE_DATAPOINTS[HKType.SWITCH]["on"].kwarg == "STATE"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/mapper/test_datapoints.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'homekit_bridge.mapper.datapoints'`.

- [ ] **Step 3: Implement**

Create `src/homekit_bridge/mapper/datapoints.py`:
```python
"""Pure HM-datapoint ↔ HomeKit-characteristic mapping tables.

No I/O, no HAP imports.  The bridge consults these to route incoming
``ccu3.state`` events onto ``accessory.update_state`` and to wire writable
characteristics back to the correct Homematic datapoint.
"""

from dataclasses import dataclass

from homekit_bridge.models import HKType


@dataclass(frozen=True)
class DP:
    """One datapoint mapping.

    ``kwarg`` is the ``update_state`` argument name (read direction) or the
    semantic characteristic name (write direction).  ``scale`` converts between
    Homematic units and HomeKit units: read does ``value * scale``, write does
    ``value / scale`` (e.g. blind LEVEL 0..1 ↔ HomeKit position 0..100).
    """

    kwarg: str
    scale: float = 1.0


READ_DATAPOINTS: dict[HKType, dict[str, DP]] = {
    HKType.THERMOSTAT: {
        "ACTUAL_TEMPERATURE": DP("current_temp"),
        "SET_POINT_TEMPERATURE": DP("target_temp"),
        "HUMIDITY": DP("humidity"),
    },
    HKType.SWITCH:      {"STATE": DP("on")},
    HKType.OUTLET:      {"STATE": DP("on")},
    HKType.CONTACT:     {"STATE": DP("contact_detected")},
    HKType.MOTION:      {"MOTION": DP("motion_detected")},
    HKType.TEMPERATURE: {"ACTUAL_TEMPERATURE": DP("temperature")},
    HKType.HUMIDITY:    {"HUMIDITY": DP("humidity")},
    HKType.COVER:       {"LEVEL": DP("position", scale=100.0)},
    HKType.LIGHTBULB:   {"STATE": DP("on"), "LEVEL": DP("brightness", scale=100.0)},
}

WRITE_DATAPOINTS: dict[HKType, dict[str, DP]] = {
    HKType.THERMOSTAT: {"target_temp": DP("SET_POINT_TEMPERATURE")},
    HKType.SWITCH:     {"on": DP("STATE")},
    HKType.OUTLET:     {"on": DP("STATE")},
    HKType.COVER:      {"position": DP("LEVEL", scale=100.0)},
    HKType.LIGHTBULB:  {"on": DP("STATE"), "brightness": DP("LEVEL", scale=100.0)},
}


def read_update(hk_type: HKType, key: str, value):
    """Return ``{update_kwarg: value*scale}`` for a HM datapoint, or None if irrelevant."""
    dp = READ_DATAPOINTS.get(hk_type, {}).get(key)
    if dp is None:
        return None
    return {dp.kwarg: value * dp.scale if dp.scale != 1.0 else value}
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/mapper/test_datapoints.py -q` → all pass.

- [ ] **Step 5: Lint + full suite + commit**

```bash
ruff check --fix src tests && pytest -q
git add src/homekit_bridge/mapper/datapoints.py tests/mapper/test_datapoints.py
git commit -m "feat: pure HM-datapoint <-> HomeKit-characteristic mapping tables"
```

---

### Task 2: `hap/accessories.py` — Thermostat-Feuchte/Range + `writable_characteristics()`

**Files:**
- Modify: `src/homekit_bridge/hap/accessories.py`
- Test: `tests/hap/test_accessories.py`

This task is **additive**: it adds `writable_characteristics()` to the writable accessory classes and extends `ThermostatAccessory`. The existing `on_set` constructor params stay for now (removed in Task 4), so nothing breaks.

- [ ] **Step 1: Failing tests**

Append to `tests/hap/test_accessories.py`:
```python
# ---------------------------------------------------------------------------
# writable_characteristics() + thermostat humidity / range
# ---------------------------------------------------------------------------

def test_thermostat_has_humidity_characteristic(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(current_temp=25.0, target_temp=4.5, humidity=40)
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("CurrentTemperature").value == 25.0
    assert svc.get_characteristic("TargetTemperature").value == 4.5
    assert svc.get_characteristic("CurrentRelativeHumidity").value == 40


def test_thermostat_target_temperature_allows_low_setpoint(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    # 4.5 °C must be accepted (HmIP frost) — default HAP min is 10
    acc.update_state(target_temp=4.5)
    assert acc.get_service("Thermostat").get_characteristic("TargetTemperature").value == 4.5


def test_writable_characteristics_per_type(driver):
    assert set(SwitchAccessory(driver, "s").writable_characteristics()) == {"on"}
    assert set(OutletAccessory(driver, "o").writable_characteristics()) == {"on"}
    assert set(LightbulbAccessory(driver, "l").writable_characteristics()) == {"on", "brightness"}
    assert set(CoverAccessory(driver, "c").writable_characteristics()) == {"position"}
    assert set(ThermostatAccessory(driver, "t").writable_characteristics()) == {"target_temp"}
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/hap/test_accessories.py::test_thermostat_has_humidity_characteristic -q`
Expected: FAIL — `AttributeError`/`ValueError` (no CurrentRelativeHumidity characteristic), or `update_state() got an unexpected keyword argument 'humidity'`.

- [ ] **Step 3: Extend ThermostatAccessory**

In `src/homekit_bridge/hap/accessories.py`, replace the `ThermostatAccessory` class body (`__init__` + `update_state`) with:
```python
    def __init__(
        self,
        driver: AccessoryDriver,
        name: str,
        on_set: Optional[Callable[[float], None]] = None,
    ) -> None:
        super().__init__(driver, name)
        svc = self.add_preload_service("Thermostat", chars=["CurrentRelativeHumidity"])
        self._char_current = svc.get_characteristic("CurrentTemperature")
        self._char_target = svc.get_characteristic("TargetTemperature")
        self._char_humidity = svc.get_characteristic("CurrentRelativeHumidity")
        self._char_hc_current = svc.get_characteristic("CurrentHeatingCoolingState")
        self._char_hc_target = svc.get_characteristic("TargetHeatingCoolingState")
        self._char_units = svc.get_characteristic("TemperatureDisplayUnits")
        # HmIP setpoint range (default HAP min 10 would reject frost-protection 4.5 °C)
        self._char_target.override_properties(
            properties={"minValue": 4.5, "maxValue": 30.5, "minStep": 0.5}
        )
        # Present as a heating thermostat (real mode mapping is out of scope)
        self._char_hc_current.set_value(1)
        self._char_hc_target.set_value(1)
        if on_set:
            _wire_setter(self._char_target, on_set)

    def update_state(
        self,
        current_temp: Optional[float] = None,
        target_temp: Optional[float] = None,
        humidity: Optional[float] = None,
    ) -> None:
        if current_temp is not None:
            self._char_current.set_value(current_temp)
        if target_temp is not None:
            self._char_target.set_value(target_temp)
        if humidity is not None:
            self._char_humidity.set_value(humidity)

    def writable_characteristics(self) -> dict:
        return {"target_temp": self._char_target}
```

- [ ] **Step 4: Add `writable_characteristics()` to the other writable classes**

Add the method to each of these classes (place it after their `update_state`):

`SwitchAccessory`:
```python
    def writable_characteristics(self) -> dict:
        return {"on": self._char_on}
```
`OutletAccessory`:
```python
    def writable_characteristics(self) -> dict:
        return {"on": self._char_on}
```
`LightbulbAccessory`:
```python
    def writable_characteristics(self) -> dict:
        return {"on": self._char_on, "brightness": self._char_brightness}
```
`CoverAccessory`:
```python
    def writable_characteristics(self) -> dict:
        return {"position": self._char_target}
```

- [ ] **Step 5: Run, confirm PASS**

Run: `pytest tests/hap/test_accessories.py -q` → all pass (existing on_set tests still green; new tests pass).

- [ ] **Step 6: Lint + full suite + commit**

```bash
ruff check --fix src tests && pytest -q
git add src/homekit_bridge/hap/accessories.py tests/hap/test_accessories.py
git commit -m "feat: thermostat humidity + setpoint range; writable_characteristics()"
```

---

### Task 3: `hap/bridge.py` — datenpunkt-bewusstes Lesen + zentrales Schreib-Wiring

**Files:**
- Modify: `src/homekit_bridge/hap/bridge.py`
- Test: `tests/hap/test_bridge.py`

- [ ] **Step 1: Failing tests**

Append to `tests/hap/test_bridge.py`:
```python
def test_thermostat_routes_datapoints_without_clobber(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Order mirrors the real payload: ACTUAL_TEMPERATURE is NOT last; BOOST_MODE is.
    for k, v in [("ACTUAL_TEMPERATURE", 25.0), ("HUMIDITY", 40),
                 ("SET_POINT_TEMPERATURE", 4.5), ("BOOST_MODE", False)]:
        bus.publish("ccu3.state", {"address": "TH:1", "key": k, "value": v})
    svc = bridge.accessories[0].get_service("Thermostat")
    assert svc.get_characteristic("CurrentTemperature").value == 25.0
    assert svc.get_characteristic("CurrentRelativeHumidity").value == 40
    assert svc.get_characteristic("TargetTemperature").value == 4.5


def test_thermostat_set_publishes_set_point_temperature(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic("TargetTemperature")
    char.client_update_value(21.0)
    assert ("TH:1", "SET_POINT_TEMPERATURE", 21.0) in ccu3.set_calls


def test_switch_set_publishes_state(driver, store, bus, ccu3):
    store.set_mapping("SW:1", exported=True, hk_type=HKType.SWITCH, name="Lamp")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Switch").get_characteristic("On")
    char.client_update_value(True)
    assert ("SW:1", "STATE", True) in ccu3.set_calls
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/hap/test_bridge.py::test_thermostat_routes_datapoints_without_clobber -q`
Expected: FAIL — CurrentTemperature ends up 0.0 / False (BOOST_MODE clobbers) under the old `_on_ccu3_state`.

- [ ] **Step 3: Update imports**

In `src/homekit_bridge/hap/bridge.py`, add to the existing `from homekit_bridge.mapper...` import area:
```python
from homekit_bridge.mapper.datapoints import WRITE_DATAPOINTS, read_update
```
Also ensure `HKType` is imported (add `from homekit_bridge.models import HKType` if not already present).

- [ ] **Step 4: Replace `_on_ccu3_state` with the datapoint-aware version**

```python
    def _on_ccu3_state(self, event: dict) -> None:
        address: str = event.get("address", "")
        acc = self._addr_index.get(address)
        mapping = self._exported.get(address)
        if acc is None or mapping is None:
            return
        upd = read_update(mapping["hk_type"], event.get("key"), event.get("value"))
        if not upd:
            return
        try:
            acc.update_state(**upd)
        except Exception:
            logger.exception("update_state failed for %s", address)
```

- [ ] **Step 5: Replace `_make_setter` with `_wire_writables`, update `_make_ccu3_accessory`**

Delete the `_make_setter` method. Add this method (e.g. where `_make_setter` was):
```python
    def _wire_writables(self, acc, address: str, hk_type: HKType) -> None:
        get_chars = getattr(acc, "writable_characteristics", None)
        if get_chars is None:
            return
        chars = get_chars()
        for semantic, dp in WRITE_DATAPOINTS.get(hk_type, {}).items():
            char = chars.get(semantic)
            if char is None:
                continue

            def setter(value, addr=address, key=dp.kwarg, scale=dp.scale):
                try:
                    self._ccu3.set_value(
                        addr, key, value / scale if scale != 1.0 else value
                    )
                except Exception:
                    logger.exception("set_value failed for %s", addr)

            char.setter_callback = setter
```
Change `_make_ccu3_accessory` so it builds without `on_set` and wires writables:
```python
    def _make_ccu3_accessory(self, mapping: dict) -> Optional[Accessory]:
        address = mapping["address"]
        name = mapping["name"] or address
        hk_type = resolve_hk_type(_ChannelProxy(address=address, hm_type=""), mapping)
        if hk_type is None:
            logger.info("Skipping %s: no HKType resolved", address)
            return None
        acc = make_accessory(driver=self._driver, hk_type=hk_type.value, name=name)
        self._wire_writables(acc, address, hk_type)
        return acc
```

- [ ] **Step 6: Run, confirm PASS**

Run: `pytest tests/hap/test_bridge.py -q` → all pass (the 3 new tests + existing reconcile/build/state tests, incl. `test_homekit_set_calls_ccu3_adapter` which still gets STATE via the new wiring).

- [ ] **Step 7: Lint + full suite + commit**

```bash
ruff check --fix src tests && pytest -q
git add src/homekit_bridge/hap/bridge.py tests/hap/test_bridge.py
git commit -m "feat: datapoint-aware state routing + central writable wiring in bridge"
```

---

### Task 4: Cleanup — `on_set` aus Accessories und `make_accessory` entfernen

**Files:**
- Modify: `src/homekit_bridge/hap/accessories.py`
- Test: `tests/hap/test_accessories.py`

After Task 3 the bridge no longer passes `on_set`; the `on_set`/`brightness_set` constructor params and the `_wire_setter` helper are dead. Remove them. Write-path behaviour is now covered by the bridge tests (Task 3).

- [ ] **Step 1: Remove obsolete on_set tests**

In `tests/hap/test_accessories.py`, DELETE these now-obsolete tests (they tested constructor-level `on_set` wiring, which no longer exists): `test_switch_on_set_callback`, `test_outlet_on_set_callback`, `test_lightbulb_on_set_callback`, the two cover on_set tests (`test_cover_*on_set*` — search for `on_set=` in cover tests), `test_thermostat`* on_set test (the one constructing `ThermostatAccessory(..., on_set=...)`), and the make_accessory on_set tests `test_make_accessory_sensor_ignores_on_set` and `test_make_accessory_switch_wires_on_set`. Keep `test_make_accessory_unknown_type_returns_none` and add the replacement below.

Add this replacement test (make_accessory still builds the right class, just without on_set):
```python
def test_make_accessory_builds_contact_without_on_set(driver):
    from homekit_bridge.hap.accessories import ContactSensorAccessory
    acc = make_accessory(driver=driver, hk_type="contact", name="Door")
    assert isinstance(acc, ContactSensorAccessory)


def test_make_accessory_builds_switch(driver):
    acc = make_accessory(driver=driver, hk_type="switch", name="Lamp")
    assert isinstance(acc, SwitchAccessory)
    assert set(acc.writable_characteristics()) == {"on"}
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/hap/test_accessories.py -q`
Expected: FAIL — the two new tests pass, but `make_accessory` / constructors still accept `on_set`; this step's RED is really the next step's guard. If everything still passes here, that's fine — proceed (the cleanup is a safe refactor verified by the unchanged suite).

- [ ] **Step 3: Remove on_set from accessory constructors + make_accessory**

In `src/homekit_bridge/hap/accessories.py`:
- Delete the `_wire_setter` helper function.
- `SwitchAccessory.__init__`, `OutletAccessory.__init__`: remove the `on_set` param and the `if on_set: _wire_setter(...)` block. Signature becomes `def __init__(self, driver, name)`.
- `LightbulbAccessory.__init__`: remove `on_set` and `brightness_set` params and their `_wire_setter` blocks.
- `CoverAccessory.__init__`, `ThermostatAccessory.__init__`: remove `on_set` param and the `if on_set: _wire_setter(...)` block.
- Remove the now-unused `Callable` import if nothing else uses it (run ruff to confirm).
- Rewrite `make_accessory` to drop `on_set` and the `inspect` usage:
```python
def make_accessory(
    driver: AccessoryDriver,
    hk_type: str,
    name: str,
) -> Optional[Accessory]:
    """Instantiate the correct accessory class for *hk_type*.

    Returns ``None`` for unknown types so callers can skip gracefully.  Writable
    characteristics are wired by the bridge via ``writable_characteristics()``.
    """
    cls = _FACTORY_MAP.get(hk_type)
    if cls is None:
        logger.warning("Unknown HKType '%s' for accessory '%s'", hk_type, name)
        return None
    return cls(driver=driver, name=name)
```
- Remove `import inspect` at the top of the file.

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/hap/test_accessories.py -q` → all pass.

- [ ] **Step 5: Lint + full suite + commit**

```bash
ruff check --fix src tests && pytest -q
git add src/homekit_bridge/hap/accessories.py tests/hap/test_accessories.py
git commit -m "refactor: drop on_set from accessories; wiring lives in the bridge"
```

---

## Self-Review-Ergebnis

- **Spec-Abdeckung:** `datapoints.py` Read+Write-Tabellen + `read_update` (T1); `_on_ccu3_state` datapoint-aware, kein Clobbering (T3); zentrales Schreib-Wiring via `writable_characteristics` + `WRITE_DATAPOINTS`, SET_POINT_TEMPERATURE statt hartem STATE (T3); Thermostat-Feuchte-Charakteristik + Range 4.5–30.5 + Heat-Default (T2); `make_accessory` ohne `on_set` (T4). Tests für Clobbering, Schreib-Datenpunkt, Feuchte, Scale.
- **Platzhalter:** keine.
- **Typ-Konsistenz:** `DP(kwarg, scale)`, `read_update(hk_type,key,value)`, `WRITE_DATAPOINTS`, `writable_characteristics()`, `_wire_writables(acc,address,hk_type)`, `update_state(current_temp,target_temp,humidity)` durchgängig identisch in allen Tasks. `make_accessory(driver,hk_type,name)` (ohne on_set) ab T4 konsistent mit T3-Aufruf.
- **Grün-Haltung:** T2 additiv (on_set bleibt vorübergehend); T3 ruft `make_accessory` ohne on_set (Param noch optional vorhanden → ok); T4 entfernt on_set, nachdem kein Caller es mehr nutzt.
