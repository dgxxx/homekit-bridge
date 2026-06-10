# QR-Pairing & Logging-Seite — Design

**Datum:** 2026-06-10
**Status:** Genehmigt (Brainstorming abgeschlossen)
**Branch:** feat/datapoint-routing (oder eigener Feature-Branch)

## Ziel

Zwei neue, voneinander unabhängige UI-Bereiche für die homekit-bridge Web-UI:

1. **Verbindung** — zeigt einen scanbaren HomeKit-Pairing-QR-Code (plus PIN und
   Pairing-Status), damit das Koppeln nicht mehr nur über das Docker-Log möglich ist.
2. **Logs** — eine Log-Ansicht im Browser, gespeist aus einem In-Memory-Ringpuffer,
   mit Level-Filter und Auto-Refresh.

Beide folgen dem bestehenden Muster: FastAPI-Endpoint unter `/api/*` (mit optionaler
Basic-Auth), Vanilla-JS-Frontend mit Polling. Keine neue Persistenz, keine Änderung an
MQTT-Source oder Mapper.

## Nicht-Ziele (YAGNI)

- Kein Download/Copy-Button für Logs.
- Kein Log-Streaming (SSE/WebSocket) — Polling reicht.
- Keine Persistenz der Logs über Neustart hinaus (reiner RAM-Ringpuffer).
- Keine Änderung an der HomeKit-Funktionalität selbst.

## Architektur-Überblick

```
Root-Logger ──► RingBufferLogHandler (deque, maxlen=500)
                        │
HAP-Driver ─────────────┼──► create_app(... , log_buffer)
  .state.pincode        │         │
  .accessory.xhm_uri()  │         ├─ GET /api/pairing        → {pin, uri, paired}
                        │         ├─ GET /api/pairing/qr.svg  → image/svg+xml (QR)
                        ▼         └─ GET /api/logs?level=…     → {records:[…]}
                  bridge_state.hap_driver
                                            ▲ Polling
                              Vanilla-JS Frontend (Tabs „Verbindung", „Logs")
```

## Komponenten

### Backend

**Neu: `src/homekit_bridge/logbuffer.py`**

- `RingBufferLogHandler(logging.Handler)`
  - Thread-sichere `collections.deque(maxlen=500)` (Default; Konstante im Modul).
  - `emit(record)` legt ein Dict ab: `{"ts": <float epoch>, "level": <str>,
    "logger": <record.name>, "message": <record.getMessage()>}`.
  - Robust gegen Formatierungsfehler (kein Crash im Logging-Pfad).
  - `records(level: str | None = None, limit: int | None = None) -> list[dict]`
    - Liefert eine Kopie der gepufferten Records, neueste zuletzt.
    - `level` filtert auf Records mit numerischem Level **>=** dem angegebenen Level
      (z. B. `level="WARNING"` zeigt WARNING + ERROR + CRITICAL).
    - `limit` schneidet auf die letzten N Records.

**`src/homekit_bridge/__main__.py`**

- In `build()`: Ringpuffer-Handler erzeugen, am Root-Logger registrieren.
  - Vor dem Hinzufügen eine evtl. vorhandene `RingBufferLogHandler`-Instanz vom
    Root-Logger entfernen → kein Doppel-Handler, wenn `build()` in Tests mehrfach läuft.
- Als Feld `log_buffer` in `AppComponents` aufnehmen.
- An `create_app(..., log_buffer=log_buffer)` durchreichen.
- `_log_pairing_info()` auf `driver.accessory.xhm_uri()` umstellen (das fehlerhafte
  handgerollte `X-HM://…`-Encoding und `_encode_setup_id()` entfernen).

**`src/homekit_bridge/web/api.py`** — neue Routen (alle mit `dependencies=api_deps`):

- `GET /api/pairing` → `{"pin": str, "uri": str, "paired": bool}`
  - `pin` aus `bridge_state.hap_driver.state.pincode.decode()`.
  - `uri` aus `bridge_state.hap_driver.accessory.xhm_uri()`.
  - `paired` aus `bridge_state.paired`.
- `GET /api/pairing/qr.svg` → `Response(media_type="image/svg+xml")`
  - QR der `uri` via `qrcode.QRCode` + `qrcode.image.svg.SvgPathImage`.
- `GET /api/logs?level=INFO` → `{"records": [ {ts, level, logger, message}, … ]}`
  - `level` optional; default alle Records.

`create_app`-Signatur bekommt einen neuen Parameter `log_buffer`. Die Pairing-Daten
laufen über das bereits vorhandene `bridge_state.hap_driver` — kein weiterer Parameter.

**`pyproject.toml`**

- `qrcode` wird feste Laufzeit-Dependency (bisher nur optionaler try/except-Import in
  `_log_pairing_info`). SVG-Rendering nutzt `qrcode.image.svg.SvgPathImage` (stdlib
  ElementTree, kein lxml/Pillow nötig).

### Frontend

**`src/homekit_bridge/web/static/index.html`**

- Zwei neue Nav-Tabs „Verbindung" und „Logs" (Muster der bestehenden `nav__tab`-Buttons
  mit `data-view`, `role="tab"`, `aria-controls`).
- View `view-pairing`:
  - QR-Karte mit `<img src="/api/pairing/qr.svg" alt="HomeKit Pairing QR">` (weißer
    Hintergrund für Scanbarkeit).
  - PIN gut lesbar, Pairing-Status („Gekoppelt" / „Nicht gekoppelt"), Hinweistext.
- View `view-logs`:
  - Level-Filter `<select>` (ALLE / DEBUG / INFO / WARNING / ERROR).
  - Log-Liste (monospaced Zeilen: Zeit · Level · Logger · Message), Level farblich.
  - Scroll-Container.

**`src/homekit_bridge/web/static/app.js`**

- State um `pairing` und `logs` erweitern; `activeView`-Typ um `"pairing"|"logs"`.
- `fetchPairing()` — einmalig beim Wechsel auf „Verbindung" (PIN/Status setzen; das
  QR-`<img>` lädt selbst über die im Browser gecachten Basic-Credentials).
- `fetchLogs()` — im Polling-Zyklus, aber **nur wenn der Logs-Tab aktiv** ist; aktueller
  Level-Filter geht als Query-Param mit. Re-Fetch auch bei Filterwechsel.
- Tab-Umschaltung ist bereits generisch über `data-view` — keine Sonderlogik nötig.

**`src/homekit_bridge/web/static/styles.css`**

- QR-Karte (zentriert, weißer Hintergrund) und Log-Viewer (Scroll-Container,
  Level-Farben) im bestehenden Stil/Variablen-System.

## Fehlerfälle (graceful — kein 500)

- `/api/pairing` und `/api/pairing/qr.svg` vor HAP-Start oder ohne `driver.accessory`
  bzw. ohne `pincode` → `HTTP 503` statt Crash.
- `qrcode`-Import- oder Renderfehler → geloggt, `HTTP 503`.
- Leerer Ringpuffer → `{"records": []}`.
- Unbekannter `level`-Wert in `/api/logs` → als „kein Filter" behandelt (oder `422`;
  Implementierung wählt eine Variante und testet sie).

## Tests (TDD — Test zuerst FAIL, dann Implementierung)

- `tests/test_logbuffer.py`
  - Record-Erfassung, Output-Shape `{ts, level, logger, message}`.
  - `maxlen`-Eviction (mehr als 500 Records → nur die letzten 500).
  - Level-Filter (`>=`-Semantik).
  - `limit`-Parameter.
- `tests/web/` (bestehende Test-App/Fixtures um `log_buffer` erweitern)
  - `/api/pairing` liefert `pin`, `uri`, `paired`.
  - `/api/pairing/qr.svg` hat `content-type: image/svg+xml` und enthält `<svg`.
  - `/api/logs` liefert Records; `?level=WARNING` filtert korrekt.
  - Auth wird auf allen drei Routen erzwungen (401 ohne Credentials, wenn Passwort gesetzt).
  - Graceful 503, wenn Pairing-Daten nicht verfügbar.
- `tests/test_main_wiring.py`
  - `AppComponents.log_buffer` vorhanden; `create_app` erhält den Puffer.

## Definition of Done

```bash
ruff check --fix src tests   # sauber (kein F401/E/W)
pytest -q                    # alle Tests grün
```

Beide Checks müssen grün sein.
