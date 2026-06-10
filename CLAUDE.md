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
  homematic/+/state  (retained, von ccu3-Dienst)
  homematic/$discovery  (retained, von ccu3-Dienst)
  solaredge/state    (retained, von solaredge-Dienst)
        │  subscribe                                   ▲ publish homematic/<addr>/set
        ▼                                              │
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
| `WEB_HOST` | nein | `0.0.0.0` | Bind-Adresse der Web-UI |
| `WEB_PORT` | nein | `8095` | Port der Web-UI |

Secrets **nie** in SQLite oder Code — nur Env-Vars.

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

- 168 Tests grün (`pytest -q`), `ruff check` sauber.
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
