# homekit-bridge

Dockerisierter Python-Dienst, der **Homematic CCU3**-Geräte (lesen + schalten) und
**SolarEdge PV**-Livedaten (nur lesen) als native HomeKit-Accessories bereitstellt.
Konfigurierbar über eine Vanilla-JS Web-UI. Ersetzt das HomeKit-Plugin der CCU3.

Spec: `docs/superpowers/specs/2026-06-07-homekit-bridge-design.md`
Plan: `docs/superpowers/plans/2026-06-07-homekit-bridge.md`
Refactor-Plan: `docs/superpowers/plans/2026-06-07-homekit-bridge-mqtt-refactor.md`

---

## Architektur

Die Bridge ist ein **MQTT-Konsument**. Gerätedaten kommen von den Diensten `ccu3` und
`solaredge`, die sie auf den MQTT-Broker publishen. Die Bridge selbst enthält keine
direkten Hardware-Adapter mehr.

```
MQTT-Broker (127.0.0.1:1883)
  homematic/+/state            (retained, von ccu3-Dienst)
  homematic/$discovery         (retained, von ccu3-Dienst; Kanäle inkl. room)
  homematic/$sysvar/+/state    (retained, von ccu3-Dienst; boolesche Systemvariablen)
  solaredge/state              (retained, von solaredge-Dienst)
        │  subscribe                                   ▲ publish homematic/<addr>/set
        ▼                                              │   bzw. homematic/$sysvar/<name>/set
┌─────────────────────────────────────────────────────────────────┐
│  Docker-Container · Python 3.12                                  │
│  MqttSource   device_mapper                                      │
│  hap_bridge (HAP-python)   web (FastAPI + Vanilla-JS)            │
│  config (SQLite)                                                 │
└─────────────────────────────────────────────────────────────────┘
            │                                       │
            ▼                                       ▼
  Apple Home (anzeigen/schalten)          Browser (Konfig-UI)
```

Kommunikation zwischen Subsystemen über einen **In-Process-Eventbus** (`events.py`).
`MqttSource` ist ein Drop-in für den früheren `Ccu3Adapter` — gleiche Schnittstelle
(`list_devices()`, `set_value()`, `connected`, `start()`), gleiche Bus-Topics
(`ccu3.state`, `solaredge.data`). Der Rest der Bridge ist unangetastet.

**CCU3-Systemvariablen (Sysvars):** Boolesche Systemvariablen (z. B. „Kachelofen")
kommen retained auf `homematic/$sysvar/<name>/state` (`{"STATE": bool}`) und sind über
`homematic/$sysvar/<name>/set` schaltbar — sofern der `ccu3`-Dienst sie in
`CCU3_SYSTEM_VARIABLES` freigegeben hat. In der Bridge laufen sie unter der
Synthetik-Adresse `sysvar:<name>` (hm_type `SYSVAR_BOOL`) durch die **unveränderte**
Geräte-Pipeline: `MqttSource` reicht sie als Pseudo-Kanäle (Raum „System-Variablen") in
`list_devices()` durch, der User vergibt in der Web-UI HK-Typ (Default-Vorschlag: Switch)
+ Export, und Reconcile baut daraus ein normales Accessory. Read-only-Typen
(Contact/Motion) sind ebenfalls wählbar. Kein neuer UI-/HAP-Code nötig.

**Bekannte Einschränkung:** `solaredge/state` enthält kein Tagesenergie-Feld →
`PVData.energy_today_kwh = 0.0`. Das PV-Energie-Accessory zeigt 0 kWh. Falls benötigt,
muss der `solaredge`-Dienst ein Energie-Feld publishen.

---

## Verzeichnisstruktur

```
homekit-bridge/
├── pyproject.toml
├── Dockerfile
├── homekit-bridge.yaml      # Docker-Compose (aktive Datei)
├── .env.example
├── src/homekit_bridge/
│   ├── __main__.py          # Entrypoint: verkabelt alle Subsysteme
│   ├── config.py            # SQLite-backed ConfigStore
│   ├── settings.py          # Env-Var-Settings (MQTT_HOST, MQTT_PORT, …)
│   ├── events.py            # In-Process-Eventbus (thread-safe)
│   ├── models.py            # Dataclasses: Device, Channel, HKMapping, PVData
│   ├── mqttsource.py        # MqttSource: MQTT-Konsum + bus.publish
│   ├── mapper/
│   │   └── device_mapper.py # CCU3-Kanal → HK-Typ; PV → Accessory-Specs (rein, kein I/O)
│   ├── hap/
│   │   ├── bridge.py        # HAP-Bridge aufbauen, Accessories registrieren
│   │   └── accessories.py   # Accessory-Factories (Switch, Cover, Sensor, PV …)
│   └── web/
│       ├── api.py           # FastAPI-App + Routen
│       └── static/          # index.html, app.js, styles.css (kein Build-Tooling)
└── tests/
    ├── conftest.py
    ├── test_models.py / test_settings.py / test_events.py / test_config.py
    ├── test_mqttsource.py / test_main_wiring.py
    ├── mapper/   hap/   web/
```

---

## Setup & Entwicklung

```bash
# Abhängigkeiten (inkl. Dev-Tools) installieren
pip install -e '.[dev]'

# Tests ausführen
pytest -q

# Linting
ruff check src tests
```

**Env-Vars (`.env` / Shell):**

| Variable | Pflicht | Default | Beschreibung |
|---|---|---|---|
| `MQTT_HOST` | nein | `127.0.0.1` | IP/Hostname des MQTT-Brokers |
| `MQTT_PORT` | nein | `1883` | Port des MQTT-Brokers |
| `WEB_PASSWORD` | nein | — | Passwort für die Web-UI (HTTP Basic) |
| `STATE_DIR` | nein | `./state` | Verzeichnis für SQLite-DB + HAP-Pairing |
| `HOMEKIT_PIN` | nein | random | Fester HomeKit-Setup-Code (`ddd-dd-ddd`). Siehe unten. |
| `HOMEKIT_MAC` | nein | random | Feste Bridge-Identität (`XX:XX:XX:XX:XX:XX`). Siehe unten. |
| `WEB_HOST` | nein | `0.0.0.0` | Bind-Adresse der Web-UI |
| `WEB_PORT` | nein | `8095` | Port der Web-UI |
| `PV_ENABLED` | nein | `false` | PV/Solar-Accessories in HomeKit erzeugen. Standard aus — siehe unten. |

Secrets **nie** in SQLite oder Code — nur Env-Vars.

**`HOMEKIT_PIN` / `HOMEKIT_MAC` — stabile Pairing-Identität:** pyhap persistiert in
`hap.state` zwar `mac`, Schlüssel und `paired_clients`, **nicht aber den Pincode** — der
wird bei *jedem* Start neu generiert. Ohne `HOMEKIT_PIN` ändert sich der Setup-Code also
laufend (relevant nur für *neue* Geräte; bestehende Pairings bleiben über die gespeicherten
Schlüssel gültig). Mit gesetztem `HOMEKIT_PIN` ist der Code stabil. `HOMEKIT_MAC` legt die
Bridge-Identität fest: bei vorhandener `hap.state` wird der dort gespeicherte Wert geladen
(muss übereinstimmen), geht `hap.state` aber verloren, sorgt `HOMEKIT_MAC` dafür, dass die
**gleiche** Identität neu entsteht → kein Re-Pairing nötig. Beide werden als Konstruktor-
Argument an den `AccessoryDriver` durchgereicht (`__main__.py`). Sind sie leer/ungesetzt,
würfelt pyhap wie bisher zufällige Werte.

**`PV_ENABLED` — PV-Accessories aus/an:** HomeKit kennt **keine** native Watt-/kWh-
Charakteristik, die die Standard-Home-App anzeigt. Die vier PV-Accessories
(LightSensor mit Watt als „Lux", Eve-Power als getarnter Switch, Battery, Producing)
wirken dort verwirrend, und `energy_today_kwh` ist ohnehin immer `0` (s. u.). Deshalb
ist `PV_ENABLED` **standardmäßig aus** — die Bridge baut dann keine PV-Accessories und
ignoriert `solaredge.data`-Events (PV-Daten bleiben in der Web-UI sichtbar). Truthy-Werte:
`1`, `true`, `yes`, `on`. Der Schalter wird in `__main__.py` aus `settings.pv_enabled` an
`HomeKitBridge(pv_enabled=…)` durchgereicht.

---

## Konventionen

- **TDD:** Erst Test schreiben (FAIL), dann implementieren (PASS), dann committen.
- **Python 3.12**, Type Hints durchgehend; dataclasses für Datenmodelle.
- **Kein I/O im Mapper** — `device_mapper.py` ist eine reine Funktion, trivial testbar.
- **Frontend:** reines HTML/CSS/Vanilla-JS — kein Framework, kein Build-Schritt.
- **Secrets per Env-Var**, nie in der DB.
- **SQLite** (stdlib `sqlite3`) für Persistenz; kein ORM.
- Zeilen max. 100 Zeichen (ruff).

### Definition of Done (je Phase / Commit)

Eine Aufgabe gilt erst als fertig, wenn **beide** Checks grün sind:

```bash
ruff check --fix src tests   # Linting + Auto-Fix (vor jedem Commit ausführen)
pytest -q                    # alle Tests grün
```

Nur `pytest` grün reicht nicht — `ruff check` muss ebenfalls sauber sein (kein F401, kein E,
kein W). Hintergrund: In Phase 2 und 3 wurden F401-Importfehler committet, weil ruff
nicht mitgeprüft wurde.

---

## Projektstatus

**v2 (MQTT-Refactor) abgeschlossen** — Stand 2026-06-07.

- 178 Tests grün (`pytest -q`), `ruff check` sauber.
- Bridge ist reiner MQTT-Konsument; `ccu3`- und `solaredge`-Adapter sind eliminiert.
- Daten kommen von den Quell-Diensten `ccu3` und `solaredge` via MQTT.

### Phasenstatus

| # | Phase | Status |
|---|---|---|
| 0-1 | Scaffold + Core (models, settings, events, SQLite) | abgeschlossen |
| 2 | CCU3-Adapter (XML-RPC + Callback + Reconnect) | abgeschlossen (entfernt in MQTT-Refactor) |
| 3 | SolarEdge-Adapter (Modbus TCP) | abgeschlossen (entfernt in MQTT-Refactor) |
| 4 | Device-Mapper (rein, kein I/O) | abgeschlossen |
| 5 | HAP-Bridge (Accessory-Factories + Wiring) | abgeschlossen |
| 6 | Web-API (FastAPI) | abgeschlossen |
| 7 | Frontend (Vanilla-JS: Dashboard + Tabelle + Solar) | abgeschlossen |
| 8 | Integration, Docker, README | abgeschlossen |
| — | MQTT-Refactor (E1-E5) | abgeschlossen |

---

## Scope — Grenzen

Folgendes ist **nicht** enthalten:
- Cloud-Anbindungen oder externe APIs
- Historische Langzeit-Statistiken (nur rudimentäre Verlaufsanzeige in UI)
- User-Management (nur optionaler Single-Passwort-Schutz)
- Automatisierungen (nur Anzeigen + Schalten)
- HomeKit-Pairing ist ein manueller Schritt (PIN aus dem Docker-Log)

Scope-Erweiterungen → erst Rücksprache mit team-lead.
