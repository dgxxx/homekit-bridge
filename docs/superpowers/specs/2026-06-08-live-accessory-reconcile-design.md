# Live-Reconcile der HomeKit-Accessories (+ Bug-B-Fix) — Design

**Datum:** 2026-06-08
**Status:** Genehmigt, bereit für Implementierungsplan
**Repo:** `homekit-bridge` (eigenes Git-Repo)

## Problem

Ein in der Web-UI exportiertes Gerät (z.B. `0000DD898F35C7:1`, „Tür Arbeitszimmer",
Contact-Sensor) erscheint nicht in Apple HomeKit. Die Diagnose ergab zwei Defekte:

### Bug A — Export wirkt erst beim Bridge-Start
`HomeKitBridge.build()` liest die Exporte **einmalig beim Start** aus der SQLite und
registriert die Accessories. Der Web-Export (`POST /api/devices/{address}`) schreibt nur
das Mapping (`config_store.set_mapping`) — er registriert **kein** Accessory bei der
laufenden HAP-Bridge. Es gibt keinen dynamischen Add-Pfad.

**Beleg:** Container gestartet `2026-06-07T21:30Z`, Mapping geschrieben `2026-06-08 13:20`
(~16 h später). `build()` lief mit alter Config; der Export wurde nie gesehen. DB-Eintrag
korrekt: `exported=1, hk_type='contact', name='Tür Arbeitszimmer'`.

### Bug B — ein Neustart würde die ganze Bridge crashen
`hap/bridge.py::_build_ccu3_accessories` ruft `make_accessory(...)` für **jeden** Kanal mit
`on_set=_make_setter(address)` auf. Read-only-Sensoren (`contact`/`temperature`/`humidity`/
`motion`) akzeptieren `on_set` in ihrem `__init__` nicht → **TypeError**. `build()`/`main()`
fangen das nicht ab → der gesamte Bridge-Start bricht ab; alle bisher funktionierenden
Geräte verschwinden. Verletzt das Design-Prinzip „exportiert … kein Crash".

**Beleg (empirisch reproduziert):**
```
make_accessory(hk_type='contact',  on_set=...) -> TypeError: ContactSensorAccessory.__init__() got an unexpected keyword argument 'on_set'
make_accessory(hk_type='switch',   on_set=...) -> OK (SwitchAccessory)
make_accessory(hk_type='contact')              -> OK (ContactSensorAccessory)
```
`make_accessory` ist in keinem Test mit `on_set` für Sensoren abgedeckt → nie aufgefallen.

Der Contact-Sensor ist der erste exportierte Read-only-Sensor; deshalb ist er jetzt
unsichtbar (Bug A) und ein naiver Neustart würde wegen Bug B alles lahmlegen.

## Verifizierte pyhap-Fakten (Grundlage des Designs)

- `AccessoryDriver.config_changed()` existiert: `increment_config_version()` + `persist()` +
  `update_advertisement()` → iOS lädt die Accessory-Liste neu (c#-Bump + mDNS).
- `update_advertisement()` macht intern bereits `self.loop.call_soon_threadsafe(...)` — der
  mDNS-Teil ist also schon loop-sicher.
- `Bridge.add_accessory(acc)` vergibt eine freie AID und legt `acc` in `bridge.accessories`
  (ein `{aid: acc}`-Dict). Entfernen: `del bridge.accessories[aid]` (keine offizielle
  Remove-Methode, aber der Pfad ist stabil).
- `driver.loop` ist ab Konstruktion vorhanden (Instanz-Attribut).
- `EventBus.publish` ist **synchron** — Handler laufen im Thread des Publishers (hier der
  Web-/Uvicorn-Thread). Daraus folgt die Thread-Sicherheits-Anforderung unten.

## Architektur

Die Web-Schicht bleibt von HAP entkoppelt: der POST publisht ein `config.changed`-Event auf
den bestehenden In-Process-Eventbus; `HomeKitBridge` abonniert es und gleicht den laufenden
Accessory-Bestand gegen die SQLite-Exporte ab. Der eigentliche HAP-Eingriff wird auf den
Driver-Event-Loop marshallt, damit `bridge.accessories` race-frei mutiert wird.

```
POST /api/devices/{addr}
  → config_store.set_mapping(...)            (SQLite)
  → bus.publish("config.changed", {address}) (synchron, Web-Thread)
        ▼
HomeKitBridge.reconcile()                    (Web-Thread)
  diff: list_exported()  vs  self._exported
  → driver.loop.call_soon_threadsafe(_apply, to_add, to_remove)
        ▼
HomeKitBridge._apply(to_add, to_remove)      (Driver-Loop-Thread, race-frei)
  remove: del hap_bridge.accessories[aid]; Indizes bereinigen
  add:    _make_ccu3_accessory(); hap_bridge.add_accessory(); indexieren
  wenn ≥1 Änderung: driver.config_changed()
```

## Komponenten & Änderungen

### 1. `hap/accessories.py` — Bug-B-Fix
`make_accessory` übergibt `on_set` nur, wenn die Ziel-Klasse es im Konstruktor akzeptiert:

```python
import inspect
...
def make_accessory(driver, hk_type, name, on_set=None):
    cls = _FACTORY_MAP.get(hk_type)
    if cls is None:
        logger.warning("Unknown HKType '%s' for accessory '%s'", hk_type, name)
        return None
    kwargs = {"driver": driver, "name": name}
    if on_set is not None and "on_set" in inspect.signature(cls.__init__).parameters:
        kwargs["on_set"] = on_set
    return cls(**kwargs)
```

Caller dürfen `on_set` weiterhin immer mitgeben; read-only Sensoren ignorieren es.

### 2. `hap/bridge.py` — Helper, Indizes, Reconcile, Apply

**Helper (DRY, von Build und Apply genutzt):**
```python
def _make_ccu3_accessory(self, mapping: dict) -> Optional[Accessory]:
    address = mapping["address"]
    name = mapping["name"] or address
    hk_type = resolve_hk_type(_ChannelProxy(address=address, hm_type=""), mapping)
    if hk_type is None:
        logger.info("Skipping %s: no HKType resolved", address)
        return None
    acc = make_accessory(
        driver=self._driver, hk_type=hk_type.value, name=name,
        on_set=self._make_setter(address),
    )
    return acc
```
`_make_setter(addr)` wird zur Methode (statt lokaler Closure), damit beide Pfade sie nutzen.

**Erst-Build** (`_build_ccu3_accessories`) ruft den Helper je Mapping in einem try/except
auf (eine kaputte Mapping wird geloggt und übersprungen, Start läuft weiter) und füllt
`self._addr_index[address] = acc` **und** `self._exported[address] = mapping`.

**Neuer Index:** `self._exported: dict[str, dict]` (address → genutztes Mapping mit
`hk_type`/`name`), um Änderungen zu erkennen. `_addr_index` bleibt (address → Accessory).

**`reconcile()`** (Handler-Thread):
```python
def reconcile(self, _event=None) -> None:
    desired = {m["address"]: m for m in self._store.list_exported()}
    to_add, to_remove = [], []
    for addr, m in desired.items():
        cur = self._exported.get(addr)
        if cur is None:
            to_add.append(m)
        elif cur.get("hk_type") != m.get("hk_type"):
            to_remove.append(addr); to_add.append(m)   # ersetzen — nur bei Typwechsel
    for addr in self._exported:
        if addr not in desired:
            to_remove.append(addr)                       # un-exportiert
    if not to_add and not to_remove:
        return
    self._driver.loop.call_soon_threadsafe(self._apply, to_add, to_remove)
```
(`hk_type` im Mapping ist ein `HKType`-Enum oder None — Enum-Vergleich ist eindeutig.)

**Bewusst nur `hk_type` als Änderungs-Kriterium, NICHT `name`:** Der in HomeKit
relevante Name und die Raumzuordnung leben in der Apple Home App, gespeichert an der
**AID** des Accessories. Ein Replace nur wegen einer Namensänderung in der Bridge-UI würde
diese AID neu vergeben und damit Raum-/Namens-/Automationszuordnung des Nutzers zerstören —
für rein kosmetischen Nutzen. Eine Namensänderung in der UI wirkt daher erst nach einem
Neustart (der UI-Name ist nur das initiale Label); Export, Un-Export und hk_type-Wechsel
wirken live.

**`_apply(to_add, to_remove)`** (Driver-Loop-Thread):
```python
def _apply(self, to_add, to_remove) -> None:
    changed = False
    for addr in to_remove:
        acc = self._addr_index.pop(addr, None)
        self._exported.pop(addr, None)
        if acc is not None and acc.aid in self.hap_bridge.accessories:
            del self.hap_bridge.accessories[acc.aid]
            changed = True
    for m in to_add:
        try:
            acc = self._make_ccu3_accessory(m)
        except Exception:
            logger.exception("Build failed for %s", m.get("address"))
            continue
        if acc is None:
            continue
        self.hap_bridge.add_accessory(acc)
        self._addr_index[m["address"]] = acc
        self._exported[m["address"]] = m
        changed = True
    if changed:
        self._driver.config_changed()
```

**Subscription:** `build()` ergänzt `self._bus.subscribe("config.changed", self.reconcile)`.

### 3. `web/api.py` — Event publizieren
`create_app(...)` bekommt einen neuen Parameter `bus: EventBus`. Der POST-Handler publisht
nach erfolgreichem `set_mapping`:
```python
config_store.set_mapping(address, exported=body.exported, hk_type=hk_type, name=body.name)
bus.publish("config.changed", {"address": address})
return {"status": "ok", "address": address}
```

### 4. `__main__.py` — Verdrahtung
`build()` übergibt `bus=bus` an `create_app(...)`. Sonst unverändert.

## Fehlerbehandlung / Threading

- Diff (`reconcile`) läuft im Handler-Thread; SQLite-Zugriff ist lock-geschützt.
- HAP-Mutation (`_apply`) ausschließlich im Driver-Loop via `call_soon_threadsafe` → keine
  Races auf `bridge.accessories`.
- `_apply` fängt Build-Fehler pro Accessory ab und ruft `config_changed()` nur bei ≥1
  erfolgreicher Änderung.
- Events vor `driver.start()` sind unkritisch — `call_soon_threadsafe` queued bis der Loop
  läuft.
- `EventBus` schluckt Handler-Exceptions bereits (kann den POST nicht stören).

## Tests

- `hap/test_accessories.py`: `make_accessory` mit Sensor+`on_set` liefert das Accessory (kein
  TypeError); Switch+`on_set` verdrahtet den Setter; unbekannter Typ → None.
- `hap/test_bridge.py`:
  - Build mit Contact-Export registriert das Accessory, kein Crash; kaputte Mapping wird
    übersprungen, andere bleiben.
  - `reconcile`/`_apply` über einen **Fake-Driver**, dessen `loop.call_soon_threadsafe(fn,*a)`
    `fn(*a)` synchron ausführt und der ein zählbares `config_changed()` hat:
    - Hinzufügen: Accessory in `hap_bridge.accessories` + `config_changed` aufgerufen.
    - Un-Export: Accessory entfernt + `config_changed`.
    - hk_type-Wechsel: altes weg, neues da (Ersetzen).
    - **Name-only-Änderung: kein Replace, `config_changed` NICHT aufgerufen** (AID/Raum
      bleiben erhalten).
    - keine Änderung: `config_changed` **nicht** aufgerufen.
- `web/test_api.py`: POST `/api/devices/{addr}` publisht `config.changed` mit der Adresse
  (Fake-Bus); bestehende POST-Tests um den `bus`-Parameter ergänzt.
- `test_main_wiring.py`: `create_app` wird mit `bus` aufgerufen.

## Reihenfolge (für den Plan)

1. Bug-B-Fix (`make_accessory`) + Build-Schleife absichern — macht Neustart/Reconcile
   gefahrlos.
2. Helper-Refactor + Indizes + `reconcile`/`_apply` + Subscription.
3. Web-Wiring (`bus`-Parameter, Event publizieren) + `__main__`.

## Out of Scope

- AID-Stabilität über Neustarts hinweg (vorbestehendes pyhap-Verhalten, unberührt).
- Live-Änderung des Bridge-Pairings oder der PV-Accessories.
- **Namensänderungen wirken nicht live** (nur nach Neustart) — bewusst, um HomeKit-Raum/
  -Name an der AID zu erhalten. Raumzuordnung erfolgt ohnehin in der Apple Home App.
- Bei einem hk_type-Wechsel (selten, inhaltlich zwingend) bekommt das ersetzte Accessory eine
  neue AID und erscheint in HomeKit als neu — Raumzuordnung muss dann neu gesetzt werden.
```
