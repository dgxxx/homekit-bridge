# Thermostat-Modi (Aus / Heizung / Automatisch) — Design

**Datum:** 2026-06-10
**Status:** Genehmigt (Brainstorming abgeschlossen)
**Branch:** feat/thermostat-modes

> **Korrektur (2026-06-10, nach Live-Test):** Die Annahme „Modus wird über
> `SET_POINT_MODE` geschrieben" war falsch. Die CCU **lehnt `setValue` auf
> `SET_POINT_MODE` ab** (faultet auf allen Interfaces) — der setzbare Parameter ist
> **`CONTROL_MODE`** (0 = AUTO, 1 = MANU), empirisch bestätigt am Gerät. Daher gilt:
> **lesen `SET_POINT_MODE`, schreiben `CONTROL_MODE`.** Die Write-Dicts unten sind
> entsprechend zu lesen als `CONTROL_MODE` statt `SET_POINT_MODE`
> (Auto → `{"CONTROL_MODE": 0}`, Heat → `{"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": …}`,
> Off → `{"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": 4.5}`). Risiko 1 ist damit
> aufgelöst (kein `ccu3`-Dienst-Eingriff nötig). Hinweis: `SET_POINT_MODE` spiegelt den
> Moduswechsel erst nach einem `ccu3`-Poll-Zyklus (~60 s) wider, nicht sofort.

## Ziel

Das HomeKit-Thermostat-Accessory soll **drei Modi** abbilden — **Aus / Heizung / Automatisch**
— statt heute nur zwei (Aus / Heizung). „Automatisch" schaltet das HmIP-Gerät real in den
Wochenprogramm-/Zeitplanmodus.

Damit werden zwei Dinge erreicht:

1. **Vollständigkeit:** das Thermostat verhält sich wie in der alten CCU3-Lösung
   („Aus/Heizung/Automatisch").
2. **Kein versehentliches Ausschalten per Kachel-Tipp:** Mit drei Modi rendert die Apple
   Home-App auf der Kachel keinen simplen Ein/Aus-Schalter mehr, sondern öffnet bei Tipp die
   Detailansicht mit dem Modus-Picker (siehe Risiko 2). „Aus" bleibt also bewusst in der
   Detailansicht wählbar, kann aber nicht mehr aus Versehen auf der Kachel ausgelöst werden.

## Nicht-Ziele (YAGNI)

- **Kein Kühlen.** Die Geräte heizen real nur (`HEATING_COOLING = 0`); „Cooling" wäre nur
  theoretisch. Kein HomeKit-Cool/-Auto-mit-Kühlung.
- **Keine per-Gerät-Konfiguration / kein Freigabe-Häkchen.** Das volle 3-Modi-Modell ist
  schlicht das korrekte Thermostat-Verhalten und gilt global für alle Raumthermostate. (Die
  ursprünglich angedachte „Ausschalten erlauben"-Option entfällt.)
- **Kein BOOST/PARTY/QUICK_VETO** als HomeKit-Charakteristik (werden weiterhin ignoriert).
- **Keine Floor-/Ventilkanäle** (`CLIMATECONTROL_FLOOR_TRANSCEIVER`, HmIP-FALMOT-C12) — die
  haben nur `LEVEL`/`VALVE_STATE`, keinen Sollwert, sind also keine echten HomeKit-Thermostate.
- **Keine Änderung am `ccu3`-Dienst** (separates Projekt). Falls Risiko 1 (Schreibbarkeit von
  `SET_POINT_MODE`) durchfällt, wird das als Folgethema dokumentiert, nicht hier gelöst.

## Reale Datengrundlage (aus dem Live-MQTT-Broker erfasst)

Raumthermostate sind die Kanäle vom Typ `HEATING_CLIMATECONTROL_TRANSCEIVER` (z. B. HmIP-WTH-1,
Heizungs-Transceiver). Ihr State-Payload (`homematic/<addr>/state`) enthält u. a.:

```json
{
  "SET_POINT_TEMPERATURE": 4.5,
  "SET_POINT_MODE": 1,
  "HEATING_COOLING": 0,
  "ACTUAL_TEMPERATURE": 21.2,
  "HUMIDITY": 53,
  "ACTIVE_PROFILE": 1,
  "BOOST_MODE": false, "PARTY_MODE": false, "WINDOW_STATE": 0,
  "FROST_PROTECTION": false
}
```

- **`SET_POINT_MODE`** ist der Modus-Datenpunkt: **0 = AUTO** (Wochenprofil), **1 = MANU**
  (manueller Sollwert). Es gibt **kein** `CONTROL_MODE`.
- `HEATING_COOLING = 0` bestätigt: System im Heizbetrieb.
- „Aus" wird weiterhin über den **Frost-Sollwert 4,5 °C** signalisiert (HomeKit-Minimum ist
  10 °C), nicht über einen eigenen Datenpunkt.

## Architektur-Überblick

```
ccu3.state (homematic/<addr>/state)
   SET_POINT_MODE, SET_POINT_TEMPERATURE, ACTUAL_TEMPERATURE, HUMIDITY
        │  READ_DATAPOINTS (datapoints.py, rein)
        ▼
ThermostatAccessory.update_state(set_point_mode, target_temp, current_temp, humidity)
   merkt sich set_point_mode + setpoint, leitet HomeKit-Modus ab
        │
        ▼   HomeKit: TargetHeatingCoolingState ∈ {Off=0, Heat=1, Auto=3}

HomeKit-Write (Modus / Zieltemperatur)
        │  WRITE_DATAPOINTS + via-Converter (darf {datapoint: value, …} liefern)
        ▼  _make_setter published je Eintrag ein homematic/<addr>/set {key: value}
   Off  → {"SET_POINT_TEMPERATURE": 4.5}
   Heat → {"SET_POINT_MODE": 1, "SET_POINT_TEMPERATURE": <letzter Heiz-Sollwert>}
   Auto → {"SET_POINT_MODE": 0}
```

## Komponenten

### `mapper/datapoints.py` (rein, kein I/O)

- **READ:** `HKType.THERMOSTAT` erhält zusätzlich `"SET_POINT_MODE": DP("set_point_mode")`
  (Bestehende `ACTUAL_TEMPERATURE`/`SET_POINT_TEMPERATURE`/`HUMIDITY` bleiben.)
- **WRITE-Mechanik erweitern:** Ein `via`-Converter darf statt eines Skalars ein
  `dict[str, value]` (Datenpunkt → Wert) zurückgeben. `read_update` bleibt unverändert.
- Die Modus-Schreibung wird auf einen neuen Converter umgestellt (siehe Accessory).

### `hap/bridge.py` — `_make_setter` / `_wire_writables`

- `_make_setter` so anpassen, dass der `convert`-Rückgabewert geprüft wird:
  - **Skalar** (heutiges Verhalten) → ein Set-Befehl auf `dp.kwarg` (mit `scale`).
  - **Dict** → für jeden Eintrag ein eigener `set_value(address, key, value)`-Aufruf;
    `dp.kwarg`/`scale` werden in diesem Fall ignoriert.
- Reihenfolge der Set-Befehle bei „Heat": erst `SET_POINT_MODE`, dann `SET_POINT_TEMPERATURE`
  (dict-Insertion-Order, deterministisch).

### `hap/accessories.py` — `ThermostatAccessory`

- `valid_values` von `{"Off": 0, "Heat": 1}` auf **`{"Off": 0, "Heat": 1, "Auto": 3}`** erweitern.
- Internen Zustand `_set_point_mode` (zuletzt bekannter MANU/AUTO-Wert) halten.
- `update_state(...)` erhält zusätzlich `set_point_mode: Optional[int]`. Ableitung des
  HomeKit-Modus aus (set_point_mode, setpoint):
  - `set_point_mode == 0` → Target = Auto (3); Current = Heat (1) (System heizt nach Plan).
  - `set_point_mode == 1` & setpoint `< _OFF_THRESHOLD` (10 °C) → Target = Off (0), Current = Off (0).
  - `set_point_mode == 1` & setpoint `≥ 10 °C` → Target = Heat (1), Current = Heat (1); Sollwert
    wird in `TargetTemperature` angezeigt.
  - Kommen `SET_POINT_MODE` und `SET_POINT_TEMPERATURE` als getrennte Events, wird bei jedem
    Update aus dem **gemerkten** Modus + Sollwert neu abgeleitet (Reihenfolge-unabhängig).
- Schreib-Converter (ersetzt/ergänzt `setpoint_for_mode`), liefert ein Dict:
  - Off (0) → `{"SET_POINT_TEMPERATURE": 4.5}`
  - Heat (1) → `{"SET_POINT_MODE": 1, "SET_POINT_TEMPERATURE": <letzter Heiz-Sollwert aus
    `_char_target.value`>}`
  - Auto (3) → `{"SET_POINT_MODE": 0}`
- `TargetTemperature`-Write bleibt wie heute ein direkter `SET_POINT_TEMPERATURE`-Befehl
  (impliziert geräteseitig MANU). Der zuletzt gültige Heiz-Sollwert wird (wie bisher) nicht von
  „Off" überschrieben, damit „Heat" ihn wiederherstellen kann.
- `writable_characteristics()` bleibt `{"target_temp": _char_target, "mode": _char_hc_target}`.

## Fehlerfälle / Randbedingungen

- Unbekannter/fehlender `SET_POINT_MODE` im Read: Modus-Ableitung fällt auf die bisherige
  Setpoint-Logik zurück (Frost → Off, sonst Heat); kein Crash.
- `HEATING_COOLING == 1` (Kühlbetrieb) ist nicht im Scope; das Mapping nimmt Heizbetrieb an.
- Window-open/BOOST/PARTY verändern den HomeKit-Modus nicht (bewusst ignoriert).

## Risiken & Verifikation (als Schritte im Implementierungsplan)

1. **Schreibbarkeit von `SET_POINT_MODE` (Hauptrisiko).** Lesen ist gesichert. Ob der
   `ccu3`-Dienst bzw. die CCU `SET_POINT_MODE` als *setzbaren* Parameter akzeptiert, ist
   unbestätigt (HmIP nutzt teils statusartige Datenpunkte). **Verifikation:** an **einem**
   Thermostat in HomeKit „Automatisch" wählen und beobachten, ob die CCU real in den
   Programmmodus wechselt (bzw. zurück zu „Heizung" → MANU). Schlägt das fehl, wird ein
   alternativer Set-Parameter bzw. eine `ccu3`-Dienst-Anpassung als Folgethema dokumentiert
   (nicht Teil dieses Plans).
2. **iOS-Kachelverhalten.** Hypothese: „drei Modi ⇒ kein Ein/Aus-Toggle auf der Kachel".
   **Verifikation:** nach dem Deploy am iPhone prüfen, dass die Kachel nicht mehr versehentlich
   ausschaltet und der Modus-Picker (Aus/Heizung/Automatisch) in der Detailansicht erscheint.

## Tests (TDD — Test zuerst FAIL, dann Implementierung)

- `tests/mapper/test_datapoints.py`
  - `SET_POINT_MODE` wird gelesen → `{"set_point_mode": <int>}`.
  - WRITE-Mechanik: ein dict-liefernder Converter wird korrekt verarbeitet (Einheitentest der
    Mechanik, soweit ohne I/O testbar).
- `tests/hap/test_accessories.py`
  - `valid_values` enthält Off/Heat/Auto (0/1/3).
  - `update_state`: (mode=0) → Target Auto; (mode=1, setpoint=4.5) → Off; (mode=1, setpoint=21) →
    Heat; Reihenfolge-Unabhängigkeit (Mode-Event vor/nach Setpoint-Event).
  - Schreib-Converter: Off → `{"SET_POINT_TEMPERATURE": 4.5}`; Heat →
    `{"SET_POINT_MODE": 1, "SET_POINT_TEMPERATURE": <letzter Sollwert>}`; Auto →
    `{"SET_POINT_MODE": 0}`.
- `tests/hap/test_bridge.py`
  - `_make_setter` published bei dict-Converter mehrere `set`-Befehle (Off/Heat/Auto-Pfade):
    z. B. Auto-Write erzeugt `("<addr>", "SET_POINT_MODE", 0)`; Heat-Write erzeugt sowohl
    `SET_POINT_MODE=1` als auch `SET_POINT_TEMPERATURE=<sollwert>`.
  - Read-Pfad: `SET_POINT_MODE`-Event schaltet HomeKit-Target auf Auto; Frost-Setpoint weiterhin
    auf Off (bestehende Tests bleiben grün).
  - Skalar-Converter (Cover/Lightbulb etc.) unverändert.

## Definition of Done

```bash
ruff check --fix src tests   # sauber (kein F401/E/W)
pytest -q                    # alle Tests grün
```

Plus die zwei Live-Verifikationen (Risiko 1 + 2) durch den Nutzer nach dem Deploy.
