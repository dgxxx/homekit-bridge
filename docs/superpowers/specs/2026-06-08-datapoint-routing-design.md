# Datenpunkt-bewusstes State-Routing (Lesen + Schreiben) — Design

**Datum:** 2026-06-08
**Status:** Genehmigt, bereit für Implementierungsplan
**Repo:** `homekit-bridge` (eigenes Git-Repo)

## Problem

Ein exportiertes Thermostat (HmIP-WTH-1, Kanal `00391F29B0D1D3:1`) erscheint in HomeKit,
zeigt aber **Temperatur 0.0** und **keine Feuchte**. Zwei vorbestehende Bugs im
State-Routing (unabhängig vom Live-Reconcile):

### Bug 1 — der Datenpunkt-`key` wird ignoriert
`MqttSource._handle_ccu3_state` publisht pro Datenpunkt ein `ccu3.state`-Event **mit** `key`
(ACTUAL_TEMPERATURE, HUMIDITY, SET_POINT_TEMPERATURE, …). Aber `HomeKitBridge._on_ccu3_state`
wirft den `key` weg und ruft für **jeden** Datenpunkt `acc.update_state(value)` (positional).
Bei `ThermostatAccessory` landet damit jeder Wert in `CurrentTemperature`; es gewinnt der
**letzte** Datenpunkt im Payload. Beleg — retained State von `homematic/00391F29B0D1D3:1/state`:
```json
{"BOOST_TIME":0,"PARTY_MODE":false,"SET_POINT_TEMPERATURE":4.5,"HUMIDITY":40,...,
 "ACTUAL_TEMPERATURE":25.0,"BOOST_MODE":false}
```
Letzter Key `BOOST_MODE: false` → `CurrentTemperature = 0.0`. (Ein Switch funktioniert nur,
weil sein Kanal genau einen Datenpunkt `STATE` sendet.)

### Bug 2 — Feuchte fehlt komplett
`ThermostatAccessory` hat keine Feuchte-Charakteristik. `CurrentRelativeHumidity` ist laut
pyhap eine **optionale** Charakteristik des `Thermostat`-Service (verifiziert), wird aber
nicht angelegt.

### Bug 3 (Schreib-Pfad, latent)
`HomeKitBridge._make_setter` publisht hartkodiert den Datenpunkt `"STATE"`. Ein HomeKit-Set
der Soll-Temperatur würde fälschlich `{"STATE": <temp>}` publishen statt
`SET_POINT_TEMPERATURE`.

## Verifizierte Fakten

- Retained State enthält `ACTUAL_TEMPERATURE=25.0`, `HUMIDITY=40`, `SET_POINT_TEMPERATURE=4.5`
  auf Kanal `:1` (`HEATING_CLIMATECONTROL_TRANSCEIVER` → CLIMATECONTROL → THERMOSTAT).
- `ccu3.state`-Event-Form: `{"address", "key", "value"}` (ein Event je Datenpunkt).
- pyhap `Thermostat`-Service: Required = CurrentHeatingCoolingState, TargetHeatingCoolingState,
  CurrentTemperature, TargetTemperature, TemperatureDisplayUnits; Optional = **CurrentRelativeHumidity**, …
- `HKType` ist ein `str`-Enum; `self._exported[addr]["hk_type"]` ist ein `HKType`.

## Architektur

Eine zentrale **reine Mapping-Tabelle** im Mapper übersetzt HM-Datenpunkte ↔ HomeKit-
Charakteristiken — in beide Richtungen. Die Bridge nutzt sie sowohl zum Routen eingehender
States als auch zum Verdrahten der Schreib-Setter. Accessories werden zu reinen HAP-
Anzeigeobjekten mit semantischem `update_state(**kwargs)` und geben ihre beschreibbaren
Charakteristiken benannt nach außen (`writable_characteristics()`). HM-Datenpunkt-Wissen lebt
ausschließlich im Mapper (passt zum bestehenden „pure mapper"-Prinzip).

```
homematic/<addr>/state {key:value,...}
  → MqttSource: ccu3.state {address,key,value}   (ein Event je Datenpunkt)
  → bridge._on_ccu3_state: read_update(hk_type,key,value) → {kwarg: value*scale} | None
  → acc.update_state(**kwargs)                   (unbekannte Datenpunkte: None → ignoriert)

HomeKit SET char → setter_callback (von bridge anhand WRITE_DATAPOINTS verdrahtet)
  → ccu3.set_value(addr, hm_key, value/scale) → homematic/<addr>/set {hm_key: value}
```

## Komponenten & Änderungen

### 1. Neu: `src/homekit_bridge/mapper/datapoints.py` (pure)

```python
from dataclasses import dataclass
from homekit_bridge.models import HKType


@dataclass(frozen=True)
class DP:
    kwarg: str          # update_state kwarg (read) / semantic char name (write)
    scale: float = 1.0  # read: value*scale ; write: value/scale


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


def read_update(hk_type, key, value):
    """{kwarg: value*scale} für einen HM-Datenpunkt, oder None wenn irrelevant."""
    dp = READ_DATAPOINTS.get(hk_type, {}).get(key)
    if dp is None:
        return None
    return {dp.kwarg: value * dp.scale if dp.scale != 1.0 else value}
```
*Hinweis:* `value * dp.scale` nur bei numerischen Werten relevant (Cover/Dimmer); für
bool/temperature ist `scale=1.0` → unverändert. Bool-Werte (STATE) treffen nie auf scale≠1.

### 2. `hap/bridge.py` — Lesen datenpunkt-bewusst

`_on_ccu3_state` ersetzen:
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
(`read_update` aus `mapper.datapoints` importieren.)

### 3. `hap/bridge.py` — Schreiben zentral verdrahten

`_make_setter` entfällt. Stattdessen verdrahtet die Bridge nach dem Bauen jede beschreibbare
Charakteristik. Im Helper `_make_ccu3_accessory` (nach `make_accessory`, vor return):
```python
        self._wire_writables(acc, address, hk_type)
```
Neue Methode:
```python
    def _wire_writables(self, acc, address: str, hk_type: HKType) -> None:
        chars = acc.writable_characteristics()
        for semantic, dp in WRITE_DATAPOINTS.get(hk_type, {}).items():
            char = chars.get(semantic)
            if char is None:
                continue
            def setter(value, addr=address, key=dp.kwarg, scale=dp.scale):
                try:
                    self._ccu3.set_value(addr, key, value / scale if scale != 1.0 else value)
                except Exception:
                    logger.exception("set_value failed for %s", addr)
            char.setter_callback = setter
```
`make_accessory` verliert den `on_set`-Parameter (siehe 4); `_make_ccu3_accessory` ruft
`make_accessory(driver, hk_type.value, name)` ohne `on_set`.

### 4. `hap/accessories.py`

- `make_accessory(driver, hk_type, name)` — **kein** `on_set`-Parameter mehr; baut nur das
  Accessory. (Der `inspect.signature`-Filter entfällt; Verdrahtung macht die Bridge.)
- Jede Accessory-Klasse: internes `on_set`/`brightness_set`-Argument entfernen; stattdessen
  `writable_characteristics() -> dict[str, characteristic]` bereitstellen:
  - Switch/Outlet: `{"on": self._char_on}`
  - Lightbulb: `{"on": self._char_on, "brightness": self._char_brightness}`
  - Cover: `{"position": self._char_target}`
  - Thermostat: `{"target_temp": self._char_target}`
  - read-only Sensoren (Contact/Temperature/Humidity/Motion): `{}`
- `ThermostatAccessory`:
  - `add_preload_service("Thermostat", chars=["CurrentRelativeHumidity"])`;
    `self._char_humidity = svc.get_characteristic("CurrentRelativeHumidity")`.
  - `update_state(current_temp=None, target_temp=None, humidity=None)` setzt die drei Werte
    (jeweils nur wenn `is not None`).
  - `TargetTemperature`-Bereich auf HmIP setzen (sonst lehnt HAP Soll 4.5 °C ab):
    `self._char_target.override_properties(properties={"minValue": 4.5, "maxValue": 30.5, "minStep": 0.5})`
    (pyhap-API verifiziert; HAP-Property-Keys `minValue`/`maxValue`/`minStep`).
  - Default `TargetHeatingCoolingState`/`CurrentHeatingCoolingState` = `1` (Heat), damit
    HomeKit es als heizenden Thermostat darstellt.
  - `writable_characteristics()` → `{"target_temp": self._char_target}`.

### 5. Tests

- `tests/mapper/test_datapoints.py`:
  - `read_update(THERMOSTAT, "ACTUAL_TEMPERATURE", 25.0) == {"current_temp": 25.0}`;
    `"SET_POINT_TEMPERATURE" → target_temp`; `"HUMIDITY" → humidity`.
  - unbekannter Datenpunkt (`"BOOST_MODE"`, `"PARTY_MODE"`) → `None`.
  - Switch `"STATE" → {"on": True}`; Contact `"STATE" → {"contact_detected": ...}`.
  - Cover `"LEVEL", 0.5 → {"position": 50.0}` (Scale).
- `tests/hap/test_bridge.py`:
  - Mehrere `ccu3.state`-Events für ein Thermostat (inkl. `BOOST_MODE`, `HUMIDITY`,
    `ACTUAL_TEMPERATURE`) → `CurrentTemperature == 25.0` (kein Clobbering durch BOOST_MODE),
    `CurrentRelativeHumidity == 40`, `TargetTemperature == 4.5`.
  - Switch-State-Event → `On` gesetzt (Regression).
  - Schreiben: HomeKit-SET von `TargetTemperature` ruft
    `ccu3.set_value(addr, "SET_POINT_TEMPERATURE", <temp>)`; Switch-`On`-SET → `STATE`.
- `tests/hap/test_accessories.py`:
  - `ThermostatAccessory` hat CurrentRelativeHumidity; `update_state(humidity=40)` setzt sie;
    `update_state(current_temp=25)` setzt CurrentTemperature; `writable_characteristics()`
    enthält `target_temp`.
  - read-only Sensoren: `writable_characteristics() == {}`.
  - `make_accessory(hk_type="contact", name=...)` ohne `on_set` baut weiterhin korrekt.
- Bestehende Tests anpassen, die `make_accessory(..., on_set=...)` oder accessory-internes
  `on_set` verwenden (Switch/Cover/Thermostat-Konstruktor-Tests, make_accessory-Tests).

## Fehlerbehandlung / Threading

- `_on_ccu3_state` läuft im MQTT-Thread; liest `_addr_index`/`_exported` via `.get`
  (GIL-atomar); `update_state` in try/except (ein fehlerhafter Datenpunkt stört nichts).
- Schreib-Setter laufen im HAP-Loop-Thread; `set_value` in try/except.
- Unbekannte Datenpunkte (`read_update → None`) werden still ignoriert — kein Clobbering.

## Out of Scope

- Echtes Heiz-/Kühl-Modus-Mapping (HEATING_COOLING/SET_POINT_MODE → Heating/CoolingState) —
  vorerst Default Heat.
- `TargetRelativeHumidity`, Schwellwert-Charakteristiken.
- Cover/Dimmer sind in den Tabellen enthalten, aber nur Thermostat/Switch/Contact werden voll
  getestet; LEVEL-Skalierung für Cover/Dimmer ist gegen echte Geräte zu verifizieren.
- Bidirektionales Pairing/Reconcile — unberührt (separates Feature).
