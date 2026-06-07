# homekit-bridge

Dockerisierter Python-Dienst, der **Homematic CCU3**-Geräte (lesen + schalten) und
**SolarEdge PV**-Livedaten (nur lesen) als native HomeKit-Accessories bereitstellt.
Konfigurierbar über eine Vanilla-JS Web-UI. Ersetzt das HomeKit-Plugin der CCU3.

Spec: `docs/superpowers/specs/2026-06-07-homekit-bridge-design.md`
Plan: `docs/superpowers/plans/2026-06-07-homekit-bridge.md`

---

## Architektur

```
CCU3 (XML-RPC + Echtzeit-Callback)    SolarEdge WR (Modbus TCP :1502)
            │                                       │
            ▼                                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Docker-Container · Python 3.12                              │
│  ccu3_adapter   solaredge_adapter   device_mapper            │
│  hap_bridge (HAP-python)   web (FastAPI + Vanilla-JS)        │
│  config (SQLite)                                             │
└─────────────────────────────────────────────────────────────┘
            │                                       │
            ▼                                       ▼
  Apple Home (anzeigen/schalten)          Browser (Konfig-UI)
```

Kommunikation zwischen Subsystemen über einen **In-Process-Eventbus** (`events.py`).
Jeder Adapter ist isoliert — Ausfall einer Quelle beeinträchtigt die andere nicht.

---

## Verzeichnisstruktur

```
homekit/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── src/homekit_bridge/
│   ├── __main__.py          # Entrypoint: verkabelt alle Subsysteme
│   ├── config.py            # SQLite-backed ConfigStore
│   ├── settings.py          # Env-Var-Settings (CCU3_HOST, SOLAREDGE_HOST, …)
│   ├── events.py            # In-Process-Eventbus (thread-safe)
│   ├── models.py            # Dataclasses: Device, Channel, HKMapping, PVData
│   ├── ccu3/
│   │   ├── client.py        # XML-RPC-Client-Wrapper
│   │   ├── callback.py      # XML-RPC-Callback-Server (empfängt CCU3-Events)
│   │   └── adapter.py       # Orchestrierung + Reconnect/Backoff
│   ├── solaredge/
│   │   ├── registers.py     # SunSpec-Modbus-Registerkonstanten
│   │   └── adapter.py       # pymodbus-Poller → PVData → Eventbus
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
    ├── ccu3/   solaredge/   mapper/   hap/   web/
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
| `CCU3_HOST` | ja | — | IP/Hostname der CCU3 |
| `SOLAREDGE_HOST` | ja | — | IP/Hostname des Wechselrichters |
| `SOLAREDGE_UNIT_ID` | nein | `1` | Modbus Unit ID |
| `WEB_PASSWORD` | nein | — | Passwort für die Web-UI (HTTP Basic) |
| `STATE_DIR` | nein | `./state` | Verzeichnis für SQLite-DB + HAP-Pairing |

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

**v1 feature-complete** — Stand 2026-06-07, HEAD `9d24813`, vom Reviewer freigegeben.

- 119 Tests grün (`pytest -q`), `ruff check` sauber, Working Tree clean.
- Alle 8 Phasen implementiert + Discovery-Merge-Fix (#15) + 3 Minor-Review-Punkte
  (`ConfigStore.list_all`, `/api/solar` None-Fallback, 422-Test) erledigt.
- **Noch nicht gegen echte Hardware verifiziert.** Beim ersten Live-Connect prüfen:
  - SolarEdge: Modbus-Register-Mapping (`registers.py`) gegen echten Wechselrichter abgleichen.
  - CCU3: exakte Homematic-Kanal-Parameter (`STATE`, `LEVEL`, …) im Mapper verifizieren.

### Phasenstatus

| # | Phase | Status |
|---|---|---|
| 0-1 | Scaffold + Core (models, settings, events, SQLite) | abgeschlossen |
| 2 | CCU3-Adapter (XML-RPC + Callback + Reconnect) | abgeschlossen |
| 3 | SolarEdge-Adapter (Modbus TCP) | abgeschlossen |
| 4 | Device-Mapper (rein, kein I/O) | abgeschlossen |
| 5 | HAP-Bridge (Accessory-Factories + Wiring) | abgeschlossen |
| 6 | Web-API (FastAPI) | abgeschlossen |
| 7 | Frontend (Vanilla-JS: Dashboard + Tabelle + Solar) | abgeschlossen |
| 8 | Integration, Docker, README | abgeschlossen |
| — | Discovery-Merge-Fix + Minor-Review-Punkte | abgeschlossen |

---

## Scope v1 — Grenzen

Folgendes ist **nicht** in v1:
- Weitere Quellen (Shelly, MQTT, Zigbee …)
- Cloud-Anbindungen oder externe APIs
- Historische Langzeit-Statistiken (nur rudimentäre Verlaufsanzeige in UI)
- User-Management (nur optionaler Single-Passwort-Schutz)
- Automatisierungen (nur Anzeigen + Schalten)

Scope-Erweiterungen → erst Rücksprache mit team-lead.
