# HomeKit-Bridge für CCU3 & SolarEdge — Design

**Datum:** 2026-06-07
**Status:** Abgenommen (Design), bereit für Implementierungsplan

## Ziel

Ein eigenständiger Dienst, der Geräte aus der **Homematic CCU3** und Live-Daten der
**SolarEdge-PV-Anlage** als **HomeKit-Accessories** bereitstellt — anzeigen und schalten —
als Ersatz für das HomeKit-Plugin der CCU3.

## Scope v1

- **Quellen:** CCU3 (Homematic, lesen + schalten) und SolarEdge PV (nur lesen, Live-Werte).
- **Deployment:** Docker-Container.
- **Konfiguration:** Web-UI (Hybrid-Layout: Dashboard + Geräte-Tabelle).

Nicht in v1: weitere Quellen (Shelly, MQTT, …), Cloud-Anbindungen, User-Management,
historische Langzeit-Statistiken (Verläufe nur rudimentär in der UI).

## Architektur

```
CCU3 (XML-RPC, Echtzeit-Callback)      SolarEdge WR (Modbus TCP :1502, read-only)
            │                                       │
            ▼                                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Docker-Container · Python 3.12 Dienst                       │
│   ccu3_adapter   solaredge_adapter   device_mapper           │
│   hap_bridge (HAP-python)   web (FastAPI + Vanilla-JS)       │
│   config (SQLite)                                            │
└─────────────────────────────────────────────────────────────┘
            │                                       │
            ▼                                       ▼
   📱 Apple Home (anzeigen/schalten/Siri)    🌐 Browser (Konfig-UI)
```

## Tech-Stack

- **Python 3.12**, ausgeliefert als Docker-Image.
- **HAP-python** — HomeKit-Bridge (Accessory-Protokoll, Pairing).
- **`xmlrpc.client` + eigener XML-RPC-Callback-Server** — CCU3 lesen und Echtzeit-Events empfangen.
- **`pymodbus`** — SolarEdge per Modbus TCP pollen.
- **FastAPI + Uvicorn** — Web-UI-API + Auslieferung des statischen Frontends.
- **Frontend:** reines HTML / CSS / Vanilla JS (kein Build-Tooling).
- **SQLite** — Persistenz der Geräte-Mappings/Benennungen.

*Verworfene Alternative:* Flask (FastAPI bietet saubere async-Endpoints + API-Doku ohne Mehraufwand).

## Komponenten

1. **`ccu3_adapter`** — XML-RPC-Verbindung, Event-Callback-Server, Geräte-/Kanal-Discovery, Reconnect.
2. **`solaredge_adapter`** — Modbus-Poller (~5 s): Leistung, Ertrag, Batterie.
3. **`device_mapper`** — übersetzt CCU3-Kanäle & PV-Werte → HomeKit-Accessory-Typen (Mapping-Regeln + Overrides aus SQLite).
4. **`hap_bridge`** — baut Accessories auf, leitet Schaltbefehle an Adapter, pusht Statusänderungen an HomeKit.
5. **`web`** — FastAPI-API + Vanilla-JS-Frontend (Hybrid-Layout).
6. **`config`** — SQLite-Zugriff (Mappings, Namen, Export-Flags).

Jede Komponente hat eine klar abgegrenzte Aufgabe und eine definierte Schnittstelle und ist
isoliert testbar.

## Datenfluss

**Schalten (Apple Home → CCU3):**
Home App → `hap_bridge` (SET) → `device_mapper` → `ccu3_adapter` (`setValue` via XML-RPC) → CCU3.

**Statusänderung (CCU3 → Apple Home):**
CCU3 → ruft XML-RPC-Callback auf → `ccu3_adapter` (Event) → `hap_bridge` aktualisiert Accessory →
Home App zeigt Zustand sofort (kein Polling).

**SolarEdge:**
`solaredge_adapter` pollt ~5 s → `hap_bridge` aktualisiert PV-Accessories.

## CCU3-Typ-Mapping (v1)

| Homematic-Kanal | HomeKit-Accessory |
|---|---|
| Schaltaktor / Steckdose | Switch / Outlet |
| Dimmer | Lightbulb (mit Helligkeit) |
| Rollladen / Jalousie | Window Covering (Position 0–100 %) |
| Heizung (HmIP-eTRV) | Thermostat (Soll/Ist-Temperatur) |
| Tür-/Fensterkontakt | Contact Sensor |
| Temperatur/Feuchte | Temperature / Humidity Sensor |
| Bewegungsmelder | Motion Sensor |

Unbekannte/nicht gemappte Kanäle bleiben in der Web-UI sichtbar, werden aber nicht nach HomeKit
exportiert (iterativer Ausbau, kein Crash).

## SolarEdge-Darstellung in HomeKit (Variante C — kombiniert)

- **Lichtsensor-Trick:** aktuelle Leistung als „Lux"-Wert → echte Live-Zahl in Apple Home.
- **Eve-Custom-Merkmale:** präzise Watt & kWh, sichtbar in der Eve-App.
- **Batterie-%** nativ.
- **„PV produziert"**-Status (an/aus).
- Detaillierte Verläufe in der eigenen Web-UI.

## Web-UI (Hybrid)

- **Dashboard-Startseite:** Kachel-Überblick (aktive Geräte, PV-Leistung, Status auf einen Blick).
- **Geräte-Tabelle:** CCU3-Geräte durchsuchen, für HomeKit-Export aktivieren, HomeKit-Typ zuordnen/überschreiben, umbenennen.
- **Solar-Ansicht:** Live-Werte und einfache Verlaufsanzeige.
- Optischer Feinschliff durch den Frontend-Designer in der Umsetzung.

## Konfiguration & Pairing

- **Secrets/Verbindung** per Umgebungsvariablen / `.env`: CCU3-Host, SolarEdge-Host/Unit-ID,
  optionales Web-UI-Passwort. Nicht in der SQLite-DB.
- **Geräte-Mapping & Benennung** in SQLite (`config.db`) im Docker-Volume.
- **HomeKit-Pairing:** ein einziges Bridge-Accessory → ein QR-Code. Pairing-State im Volume
  (übersteht Updates/Neustarts).
- **Docker im Host-Network-Modus** (HAP benötigt mDNS/Bonjour im LAN) — in README dokumentiert.
- **Web-UI-Zugang:** LAN-only, optionaler einfacher Passwortschutz (eine Env-Var). Kein
  User-Management in v1.

## Fehlerbehandlung & Robustheit

- **CCU3 nicht erreichbar:** automatischer Reconnect mit Backoff; Re-Registrierung des
  Event-Callbacks nach CCU3-Neustart.
- **SolarEdge-Timeout:** letzter Wert bleibt kurz erhalten, danach „nicht verfügbar"; kein
  Gesamt-Crash.
- **Isolierte Adapter:** Ausfall einer Quelle beeinträchtigt die andere nicht.
- **Strukturiertes Logging** (Stdout) + Health-Endpoint `/health`.

## Tests

- Unit-Tests mit gemockten CCU3-/Modbus-Schnittstellen (Adapter + Mapper).
- Abdeckung von Happy-Path **und** Fehlerfällen (Reconnect, Timeout, unbekannte Kanäle).
- Reviewer prüft Qualität, Korrektheit und Testabdeckung (read-only).

## Team-Zuordnung (grob)

- **Backend (Python):** Adapter, Mapper, HAP-Bridge, FastAPI, SQLite, Tests.
- **Frontend:** Vanilla-JS-UI (Dashboard, Geräte-Tabelle, Solar-Ansicht) gegen die FastAPI-API.
- **Reviewer:** Code-Review von Backend & Tests.
- **Projektmanager:** Tasks, Priorisierung, CLAUDE.md, Scope-Wache.

## Offene Punkte für den Implementierungsplan

- Genaue SolarEdge-Modbus-Register (Single-/Three-Phase, mit/ohne Batterie) beim ersten Connect verifizieren.
- Exakte Homematic-Kanal-Parameter pro Gerätetyp (z. B. `LEVEL`, `STATE`) im Mapper hinterlegen.
- Versionierung/Migrations-Strategie für `config.db`.
```
