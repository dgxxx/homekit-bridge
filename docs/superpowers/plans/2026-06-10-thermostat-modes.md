# Thermostat-Modi (Aus / Heizung / Automatisch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das HomeKit-Thermostat als drei Modi (Aus/Heizung/Automatisch) abbilden, wobei „Automatisch" das HmIP-Gerät real über `SET_POINT_MODE` in den Wochenprogramm-Modus schaltet.

**Architecture:** Read-Pfad liest zusätzlich `SET_POINT_MODE` und leitet im Accessory reihenfolge-unabhängig den HomeKit-Modus aus (mode, setpoint) ab. Write-Pfad wird minimal verallgemeinert: ein `via`-Converter darf ein `{datapoint: value}`-Dict liefern, das `_make_setter` als mehrere `homematic/<addr>/set`-Befehle published. `valid_values` des Thermostats wird auf `{Off:0, Heat:1, Auto:3}` erweitert.

**Tech Stack:** Python 3.12, HAP-python (pyhap), reine Mapping-Tabellen (`datapoints.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-thermostat-modes-design.md`

---

## File Structure

- **Modify:** `src/homekit_bridge/mapper/datapoints.py` — `SET_POINT_MODE` in READ; WRITE-`mode`-Converter auf `writes_for_mode` umstellen.
- **Modify:** `src/homekit_bridge/hap/bridge.py` — `_make_setter` so erweitern, dass dict-liefernde Converter mehrere Set-Befehle erzeugen.
- **Modify:** `src/homekit_bridge/hap/accessories.py` — `ThermostatAccessory`: `valid_values` + Auto, `update_state(set_point_mode=…)` + `_apply_mode`, `setpoint_for_mode` → `writes_for_mode` (dict).
- **Modify:** `tests/mapper/test_datapoints.py`, `tests/hap/test_accessories.py`, `tests/hap/test_bridge.py` — neue/aktualisierte Tests.
- **Modify:** `CLAUDE.md` — Testzahl aktualisieren.

HmIP-Semantik (aus Live-Daten bestätigt): `SET_POINT_MODE` 0 = AUTO (Wochenprofil), 1 = MANU. „Aus" = Sollwert 4,5 °C. HomeKit `TargetHeatingCoolingState`: 0=Off, 1=Heat, 3=Auto (2=Cool ungenutzt). `CurrentHeatingCoolingState` kennt kein „Auto" → bei Auto zeigen wir Heat (1).

---

## Task 1: SET_POINT_MODE im Read-Pfad

**Files:**
- Modify: `src/homekit_bridge/mapper/datapoints.py`
- Test: `tests/mapper/test_datapoints.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/mapper/test_datapoints.py` zur bestehenden `test_thermostat_read_datapoints` (oder als neue Funktion) ergänzen:

```python
def test_thermostat_reads_set_point_mode():
    assert read_update(HKType.THERMOSTAT, "SET_POINT_MODE", 0) == {"set_point_mode": 0}
    assert read_update(HKType.THERMOSTAT, "SET_POINT_MODE", 1) == {"set_point_mode": 1}
```

- [ ] **Step 2: Test ausführen, FAIL bestätigen**

Run: `pytest tests/mapper/test_datapoints.py::test_thermostat_reads_set_point_mode -q`
Expected: FAIL (read_update gibt `None`, weil `SET_POINT_MODE` nicht gemappt ist).

- [ ] **Step 3: Implementieren**

In `src/homekit_bridge/mapper/datapoints.py`, im `READ_DATAPOINTS`-Eintrag für `HKType.THERMOSTAT`, die Zeile ergänzen (nach `"HUMIDITY": DP("humidity"),`):

```python
        "SET_POINT_MODE": DP("set_point_mode"),
```

- [ ] **Step 4: Test ausführen, PASS bestätigen**

Run: `pytest tests/mapper/test_datapoints.py -q`
Expected: PASS (alle datapoints-Tests grün; `BOOST_MODE`/`PARTY_MODE` liefern weiterhin `None`).

- [ ] **Step 5: Commit**

```bash
ruff check --fix src/homekit_bridge/mapper/datapoints.py tests/mapper/test_datapoints.py
git add src/homekit_bridge/mapper/datapoints.py tests/mapper/test_datapoints.py
git commit -m "feat: read SET_POINT_MODE datapoint for thermostats

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_make_setter` für dict-liefernde Converter

Verallgemeinert den Write-Pfad: gibt ein `via`-Converter ein Dict zurück, wird je Eintrag ein eigener Set-Befehl publiziert (statt eines einzelnen `dp.kwarg`-Befehls). Skalar-Converter und der Pfad ohne Converter bleiben unverändert. Dies ist Voraussetzung für den Auto/Heat-Write in Task 3.

**Files:**
- Modify: `src/homekit_bridge/hap/bridge.py`
- Test: `tests/hap/test_bridge.py`

- [ ] **Step 1: Failing tests schreiben**

In `tests/hap/test_bridge.py` anhängen (nutzt die vorhandenen Fixtures `driver`, `store`, `bus`, `ccu3`; `ccu3.set_calls` ist eine Liste von `(addr, key, value)`-Tupeln):

```python
def test_make_setter_dict_converter_publishes_each_datapoint(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    setter = bridge._make_setter("ADDR", "IGNORED", 1.0, convert=lambda v: {"A": 1, "B": 2})
    setter(99)
    assert ("ADDR", "A", 1) in ccu3.set_calls
    assert ("ADDR", "B", 2) in ccu3.set_calls
    # The declared dp.kwarg ("IGNORED") and the raw value are NOT published for a dict converter
    assert ("ADDR", "IGNORED", 99) not in ccu3.set_calls


def test_make_setter_scalar_converter_still_scales(driver, store, bus, ccu3):
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    setter = bridge._make_setter("ADDR", "LEVEL", 100.0, convert=None)
    setter(50)  # scale 100 → 0.5
    assert ("ADDR", "LEVEL", 0.5) in ccu3.set_calls
```

- [ ] **Step 2: Tests ausführen, FAIL bestätigen**

Run: `pytest tests/hap/test_bridge.py -q -k make_setter`
Expected: FAIL beim dict-Test (der heutige `_make_setter` ruft `value / scale` auf einem Dict auf → TypeError / kein passender Publish).

- [ ] **Step 3: Implementieren**

In `src/homekit_bridge/hap/bridge.py`, `_make_setter` vollständig ersetzen durch:

```python
    def _make_setter(self, addr: str, key: str, scale: float, convert=None):
        def setter(value):
            try:
                if convert is not None:
                    converted = convert(value)
                    if isinstance(converted, dict):
                        # Converter chose the datapoint(s) itself (e.g. thermostat mode):
                        # publish each as its own homematic/<addr>/set command.
                        for dp_key, dp_val in converted.items():
                            self._ccu3.set_value(addr, dp_key, dp_val)
                        return
                    value = converted
                self._ccu3.set_value(addr, key, value / scale if scale != 1.0 else value)
            except Exception:
                logger.exception("set_value failed for %s", addr)
        return setter
```

- [ ] **Step 4: Tests ausführen, PASS bestätigen**

Run: `pytest tests/hap/test_bridge.py -q`
Expected: PASS (neue make_setter-Tests grün; alle bestehenden bridge-Tests bleiben grün — die Skalar-/Cover-/Switch-Pfade sind unverändert).

- [ ] **Step 5: Commit**

```bash
ruff check --fix src/homekit_bridge/hap/bridge.py tests/hap/test_bridge.py
git add src/homekit_bridge/hap/bridge.py tests/hap/test_bridge.py
git commit -m "feat: setter converters may target multiple datapoints via dict

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: ThermostatAccessory — Auto-Modus (read + write)

Erweitert `valid_values` um Auto, fügt reihenfolge-unabhängige Modus-Ableitung aus `SET_POINT_MODE` + Sollwert hinzu, und ersetzt `setpoint_for_mode` durch `writes_for_mode`, das ein Datenpunkt-Dict liefert. Stellt zudem den WRITE-`mode`-Converter in `datapoints.py` auf die neue Methode um.

**Files:**
- Modify: `src/homekit_bridge/hap/accessories.py` (`ThermostatAccessory`)
- Modify: `src/homekit_bridge/mapper/datapoints.py` (WRITE `mode` via)
- Test: `tests/hap/test_accessories.py`

- [ ] **Step 1: Failing/aktualisierte Tests schreiben**

In `tests/hap/test_accessories.py`:

(a) Den bestehenden Test `test_thermostat_mode_valid_values_only_off_and_heat` **ersetzen** durch:

```python
def test_thermostat_mode_valid_values_off_heat_auto(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    char = acc.get_service("Thermostat").get_characteristic("TargetHeatingCoolingState")
    assert set(char.properties["ValidValues"].values()) == {0, 1, 3}
```

(b) Den bestehenden Test `test_thermostat_setpoint_for_mode` **ersetzen** durch:

```python
def test_thermostat_writes_for_mode(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(target_temp=22.0)  # establishes the last heating setpoint
    assert acc.writes_for_mode(0) == {"SET_POINT_TEMPERATURE": 4.5}        # Off
    assert acc.writes_for_mode(3) == {"SET_POINT_MODE": 0}                 # Auto
    assert acc.writes_for_mode(1) == {"SET_POINT_MODE": 1,
                                      "SET_POINT_TEMPERATURE": 22.0}       # Heat
```

(c) Neue Tests anhängen:

```python
def test_thermostat_auto_mode_maps_to_auto(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    acc.update_state(set_point_mode=0)  # HmIP AUTO
    svc = acc.get_service("Thermostat")
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3
    # Current has no "Auto" state in HomeKit → shown as Heat
    assert svc.get_characteristic("CurrentHeatingCoolingState").value == 1


def test_thermostat_mode_derivation_is_order_independent(driver):
    acc = ThermostatAccessory(driver, "Thermo")
    svc = acc.get_service("Thermostat")
    # mode event arrives BEFORE the setpoint event
    acc.update_state(set_point_mode=1)        # MANU
    acc.update_state(target_temp=4.5)         # frost → Off
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 0
    # later the device switches to AUTO
    acc.update_state(set_point_mode=0)
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3
    # and back to MANU with a real setpoint → Heat
    acc.update_state(set_point_mode=1)
    acc.update_state(target_temp=21.0)
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 1
```

- [ ] **Step 2: Tests ausführen, FAIL bestätigen**

Run: `pytest tests/hap/test_accessories.py -q -k thermostat`
Expected: FAIL — `ValidValues` ist noch `{0,1}`, `writes_for_mode`/`set_point_mode` existieren nicht.

- [ ] **Step 3: Accessory implementieren**

In `src/homekit_bridge/hap/accessories.py`, in `ThermostatAccessory.__init__`, die `valid_values`-Zeile ersetzen und Zustandsfelder ergänzen. Ersetze:

```python
        # Heating-only device: no cool/auto modes
        self._char_hc_target.override_properties(valid_values={"Off": 0, "Heat": 1})
        self._char_hc_current.set_value(1)
        self._char_hc_target.set_value(1)
```

durch:

```python
        # Heating device with HmIP schedule: Off / Heat / Auto (no cooling)
        self._char_hc_target.override_properties(
            valid_values={"Off": 0, "Heat": 1, "Auto": 3}
        )
        self._char_hc_current.set_value(1)
        self._char_hc_target.set_value(1)
        # HmIP SET_POINT_MODE: 0 = AUTO (weekly profile), 1 = MANU. Last raw setpoint
        # (may be the 4.5 °C frost value) is remembered to derive Off vs Heat.
        self._set_point_mode = 1
        self._raw_setpoint: Optional[float] = None
```

Dann die Methode `update_state` vollständig ersetzen durch:

```python
    def update_state(
        self,
        current_temp: Optional[float] = None,
        target_temp: Optional[float] = None,
        humidity: Optional[float] = None,
        set_point_mode: Optional[int] = None,
    ) -> None:
        if current_temp is not None:
            self._char_current.set_value(current_temp)
        if humidity is not None:
            self._char_humidity.set_value(humidity)
        if target_temp is not None:
            self._raw_setpoint = target_temp
            if target_temp >= self._OFF_THRESHOLD:
                # Keep the last real heating setpoint for display + Heat restore;
                # frost/eco values below 10 °C never overwrite it.
                self._char_target.set_value(target_temp)
        if set_point_mode is not None:
            self._set_point_mode = set_point_mode
        if target_temp is not None or set_point_mode is not None:
            self._apply_mode()

    def _apply_mode(self) -> None:
        """Derive HomeKit heat/cool state from SET_POINT_MODE + last setpoint."""
        if self._set_point_mode == 0:           # HmIP AUTO → HomeKit Auto
            self._char_hc_target.set_value(3)
            self._char_hc_current.set_value(1)  # Current has no "Auto"; show Heat
            return
        # MANU: frost setpoint == off, otherwise heating
        if self._raw_setpoint is not None and self._raw_setpoint < self._OFF_THRESHOLD:
            self._char_hc_current.set_value(0)
            self._char_hc_target.set_value(0)
        else:
            self._char_hc_current.set_value(1)
            self._char_hc_target.set_value(1)
```

Dann die Methode `setpoint_for_mode` vollständig ersetzen durch `writes_for_mode`:

```python
    def writes_for_mode(self, mode: int) -> dict:
        """HM datapoints realizing a HomeKit mode write.

        Off (0)  → frost setpoint (forces MANU on the device).
        Auto (3) → SET_POINT_MODE 0 (follow the HmIP weekly profile).
        Heat (1) → SET_POINT_MODE 1 (MANU) + restore the last heating setpoint
                   still held by TargetTemperature (never overwritten by "off").
        """
        if mode == 0:
            return {"SET_POINT_TEMPERATURE": self.OFF_SETPOINT}
        if mode == 3:
            return {"SET_POINT_MODE": 0}
        return {"SET_POINT_MODE": 1, "SET_POINT_TEMPERATURE": float(self._char_target.value)}
```

- [ ] **Step 4: WRITE-Converter in datapoints.py umstellen**

In `src/homekit_bridge/mapper/datapoints.py`, im `WRITE_DATAPOINTS`-Eintrag für `HKType.THERMOSTAT`, die `mode`-Zeile ändern von:

```python
        "mode": DP("SET_POINT_TEMPERATURE", via="setpoint_for_mode"),
```

zu:

```python
        "mode": DP("SET_POINT_TEMPERATURE", via="writes_for_mode"),
```

(`kwarg` bleibt als harmloser Fallback stehen; bei dict-Rückgabe wird er ignoriert.)

- [ ] **Step 5: Tests ausführen, PASS bestätigen**

Run: `pytest tests/hap/test_accessories.py -q`
Expected: PASS — neue Auto-/writes_for_mode-Tests grün; die bestehenden `test_thermostat_frost_setpoint_maps_to_off` / `test_thermostat_normal_setpoint_maps_to_heat` / `test_thermostat_update_state` / `test_thermostat_has_humidity_characteristic` bleiben grün (Default-Modus MANU ⇒ unveränderte Frost/Heat-Ableitung).

- [ ] **Step 6: Commit**

```bash
ruff check --fix src/homekit_bridge/hap/accessories.py src/homekit_bridge/mapper/datapoints.py tests/hap/test_accessories.py
git add src/homekit_bridge/hap/accessories.py src/homekit_bridge/mapper/datapoints.py tests/hap/test_accessories.py
git commit -m "feat: thermostat Off/Heat/Auto modes via SET_POINT_MODE

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Bridge end-to-end (Auto lesen + schreiben)

Verdrahtet die beiden vorherigen Tasks im echten Event-/Setter-Pfad und sichert sie mit Tests ab.

**Files:**
- Test: `tests/hap/test_bridge.py`
- (Keine Produktivänderung erwartet — falls ein Test fehlschlägt, liegt der Fix in Task 2/3.)

- [ ] **Step 1: Tests schreiben**

In `tests/hap/test_bridge.py` anhängen:

```python
def test_thermostat_auto_mode_event_sets_homekit_auto(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    svc = bridge.accessories[0].get_service("Thermostat")
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_MODE", "value": 0})
    assert svc.get_characteristic("TargetHeatingCoolingState").value == 3


def test_thermostat_mode_auto_publishes_set_point_mode(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(3)  # Auto
    assert ("TH:1", "SET_POINT_MODE", 0) in ccu3.set_calls


def test_thermostat_mode_heat_publishes_manu_and_setpoint(driver, store, bus, ccu3):
    store.set_mapping("TH:1", exported=True, hk_type=HKType.THERMOSTAT, name="Thermo")
    bridge = HomeKitBridge(driver=driver, config_store=store, ccu3_adapter=ccu3, bus=bus)
    bridge.build()
    # Heating at 21.5, then off (frost) — last heating setpoint 21.5 is retained.
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 21.5})
    bus.publish("ccu3.state", {"address": "TH:1", "key": "SET_POINT_TEMPERATURE", "value": 4.5})
    char = bridge.accessories[0].get_service("Thermostat").get_characteristic(
        "TargetHeatingCoolingState")
    char.client_update_value(1)  # Heat
    assert ("TH:1", "SET_POINT_MODE", 1) in ccu3.set_calls
    assert ("TH:1", "SET_POINT_TEMPERATURE", 21.5) in ccu3.set_calls
```

- [ ] **Step 2: Tests ausführen**

Run: `pytest tests/hap/test_bridge.py -q`
Expected: PASS — inkl. der drei neuen Tests. Die bestehenden Thermostat-Bridge-Tests
(`test_thermostat_mode_off_publishes_frost_setpoint`, `…_heat_restores_last_setpoint`,
`…_set_publishes_set_point_temperature`, `…_frost_setpoint_event_switches_mode_off`,
`…_routes_datapoints_without_clobber`) bleiben grün, weil sie `in ccu3.set_calls` prüfen und
der Default-Modus MANU ist.

- [ ] **Step 3: Volle Suite + Lint**

Run: `ruff check src tests && pytest -q`
Expected: `ruff` sauber, alle Tests grün.

- [ ] **Step 4: Commit**

```bash
git add tests/hap/test_bridge.py
git commit -m "test: end-to-end thermostat Auto read/write via bridge

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Doku — Testzahl aktualisieren

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Neue Testzahl ermitteln**

Run: `pytest -q 2>&1 | tail -1`
Notiere die Anzahl „N passed".

- [ ] **Step 2: CLAUDE.md aktualisieren**

In `CLAUDE.md` die Zeile `- 157 Tests grün (`pytest -q`), `ruff check` sauber.` auf die neue Zahl N setzen.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: bump test count after thermostat modes feature

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Definition of Done (automatisiert):**

```bash
ruff check src tests
pytest -q
```

Expected: `ruff check` sauber (kein F401/E/W), alle Tests grün.

- [ ] **Live-Verifikation 1 — Schreibbarkeit von `SET_POINT_MODE` (Hauptrisiko):**
  Nach dem Deploy an **einem** Thermostat in der Home-App „Automatisch" wählen und prüfen, ob die
  CCU real in den Programm-/Zeitplanmodus wechselt (z. B. in der CCU-WebUI: Betriebsart =
  „Auto"). Dann „Heizung" wählen → CCU sollte auf „Manu" + letzten Sollwert gehen, „Aus" → 4,5 °C.
  Schlägt der Auto-Write fehl (CCU akzeptiert `SET_POINT_MODE` nicht als setzbar), als Folgethema
  dokumentieren (alternativer Set-Parameter bzw. `ccu3`-Dienst-Anpassung) — **nicht** Teil dieses
  Plans.

- [ ] **Live-Verifikation 2 — iOS-Kachel:**
  In der Home-App prüfen, dass das Thermostat **nicht mehr per Kachel-Tipp** versehentlich
  ausschaltet und die Detailansicht den Picker „Aus / Heizung / Automatisch" zeigt.
