# HomeKit Bridge

[🇬🇧 English](README.md) · 🇩🇪 Deutsch

Ein dockerisierter Python-Dienst, der **Homematic-CCU3**-Geräte (lesen + schalten) und
**SolarEdge-PV**-Livedaten (nur lesen) als native HomeKit-Accessories bereitstellt —
konfigurierbar über eine kleine Vanilla-JS-Web-UI. Ersetzt das HomeKit-Plugin der CCU3.

## Architektur

Die Bridge ist ein **MQTT-Konsument**. Sie spricht **nicht** direkt mit der CCU3 oder dem
Wechselrichter. Zwei separate Quell-Dienste publishen Gerätedaten auf einen MQTT-Broker,
die Bridge abonniert sie:

```
  ccu3-Dienst ──┐
                ├─▶  MQTT-Broker (1883)  ◀──  homekit-bridge  ──▶  Apple Home
  solaredge ────┘                                   │
                                                     └──▶  Browser (Konfig-Web-UI)
```

Abonnierte Topics (alle retained):

| Topic | Publisher | Payload |
|---|---|---|
| `homematic/$discovery` | ccu3 | Kanalliste inkl. Raum |
| `homematic/+/state` | ccu3 | Zustand je Kanal |
| `homematic/$sysvar/+/state` | ccu3 | boolesche CCU3-Systemvariablen `{"STATE": bool}` |
| `solaredge/state` | solaredge | Wechselrichter-Livedaten |

Zum Schalten publisht die Bridge auf `homematic/<addr>/set` (bzw.
`homematic/$sysvar/<name>/set`).

> Die Quell-Dienste `ccu3` und `solaredge` sind **nicht** Teil dieses Repos. Dieses Repo
> enthält die Bridge plus einen startklaren Mosquitto-Broker (siehe
> [README_mqtt.de.md](README_mqtt.de.md)).

## Voraussetzungen

- Docker + Docker Compose auf einem Linux-Host
- Ein MQTT-Broker (mitgeliefert — siehe Compose-Stack unten)
- Die Dienste `ccu3` / `solaredge`, die auf diesen Broker publishen (für Livedaten)
- `network_mode: host` — nötig, damit HomeKits mDNS/Bonjour-Discovery das LAN erreicht und
  die Bridge den Broker unter `127.0.0.1:1883` ansprechen kann

## Einrichtung

1. **Repo** auf den Server klonen.

2. **`.env`** aus dem Beispiel erzeugen:

   ```bash
   cp .env.example .env
   ```

   Alle Werte haben sinnvolle Defaults; bei einem lokalen Broker auf demselben Host muss
   nichts geändert werden. Häufige Anpassungen:

   ```
   MQTT_HOST=127.0.0.1      # Broker-Adresse (Default)
   MQTT_PORT=1883           # Broker-Port (Default)
   WEB_PASSWORD=...          # optionales HTTP-Basic-Passwort für die Web-UI
   HOMEKIT_PIN=123-45-678    # optionaler fester Pairing-Code (siehe .env.example)
   ```

3. **Stack starten** (Bridge + Mosquitto-Broker). Die aktive Compose-Datei ist
   `homekit-bridge.yaml`; die mitgelieferten `make`-Targets kapseln sie:

   ```bash
   make start          # = docker compose -f homekit-bridge.yaml up -d
   make buildstart     # Image neu bauen, dann starten
   make logs           # Bridge-Logs verfolgen
   make restart
   make stop
   ```

   Oder Compose direkt aufrufen:

   ```bash
   docker compose -f homekit-bridge.yaml up -d
   ```

   Beim ersten Start wird das Image gebaut und `./state/` (SQLite-DB + HAP-Pairing) sowie
   `./data/` (Broker-Persistenz) werden angelegt.

4. **Web-UI öffnen** unter `http://<server-ip>:8095`.

## HomeKit-Pairing

1. Den Setup-Code im Log finden:

   ```bash
   make logs            # oder: docker compose -f homekit-bridge.yaml logs homekit-bridge
   ```

   Ohne `HOMEKIT_PIN` wird der Code **bei jedem Neustart neu erzeugt** (pyhap persistiert
   ihn nicht). Setze `HOMEKIT_PIN` in `.env`, um ihn stabil zu halten — siehe
   `.env.example`.

2. Auf dem iPhone/iPad: **Home → + → Gerät hinzufügen → Weitere Optionen**, dann den
   QR-Code (in der Web-UI / im Log) scannen oder die PIN manuell eingeben.

3. Nach dem Pairing erscheint jedes exportierte Gerät als HomeKit-Accessory unter der einen
   Bridge — kein Pairing pro Gerät.

## Geräte in der Web-UI zuordnen

1. Tab **Geräte** öffnen — alle über MQTT erkannten Kanäle sind nach Raum gruppiert
   gelistet.
2. **Export** umschalten, um einen Kanal an HomeKit zu exportieren.
3. **HomeKit-Typ** wählen (Switch, Lightbulb, Cover, Contact/Window/Door, …). Aus dem
   CCU3-Kanaltyp wird ein sinnvoller Default vorausgewählt.
4. Den **Namen** für die Home-App setzen.
5. **Speichern** — Accessories werden live abgeglichen; kein Neustart nötig.

Ein paar Typ-Hinweise:

- **Tür-/Fensterkontakte:** als `contact` exportieren (Sensor — erscheint nur in der
  Statuszeile) oder als `window`/`door` für eine vollwertige Raum-Kachel (positionsbasierter
  Service, read-only).
- **CCU3-Systemvariablen** (boolesche, vom `ccu3`-Dienst freigegebene Sysvars) erscheinen im
  Raum *„System-Variablen"* und lassen sich als Switch (Default) oder read-only Sensortyp
  exportieren.
- **PV-/Solar-Accessories** sind **standardmäßig aus** (`PV_ENABLED=false`) — HomeKit kennt
  keine native Watt-/kWh-Charakteristik, daher zeigt die Standard-Home-App sie verwirrend
  an. PV-Daten bleiben in der Web-UI unabhängig davon sichtbar.

## Konfig-Backup / -Restore

Die gesamte Konfiguration (Geräte-Mappings + HomeKit-Accessory-IDs) lässt sich als JSON
sichern und wiederherstellen:

- **Automatisch:** ein Tages-Snapshot nach `STATE_DIR/backups`, rotiert (`BACKUP_ENABLED`,
  `BACKUP_RETENTION` — siehe `.env.example`).
- **Manuell:** Web-UI-Tab **„Sicherung"** — Backup herunterladen, Upload wiederherstellen
  oder Auto-Backup laden. Die HomeKit-Accessory-IDs sind enthalten, ein Restore reproduziert
  also dieselbe Accessory-DB **ohne erneutes Pairing**.

## Persistenter Zustand

| Pfad | Inhalt |
|---|---|
| `state/mappings.db` | SQLite: Gerät → HomeKit-Typ / Name / Export-Flag + Accessory-IDs |
| `state/hap.state` | HAP-Pairing-Keys — **Löschen zerstört das Pairing** |
| `state/backups/` | rotierte Tages-Snapshots der Konfig |
| `data/` | Mosquitto-Broker-Persistenz |

Sichere `./state/`, um Pairings nicht zu verlieren. (Alle vier Pfade sind gitignored.)

## Umgebungsvariablen

Die vollständige, kommentierte Liste steht in [.env.example](.env.example). Überblick:

| Variable | Default | Zweck |
|---|---|---|
| `MQTT_HOST` | `127.0.0.1` | Broker-Host |
| `MQTT_PORT` | `1883` | Broker-Port |
| `WEB_PASSWORD` | — | optionales Web-UI-Passwort (HTTP Basic) |
| `STATE_DIR` | `./state` (im Docker `/app/state`) | persistentes Datenverzeichnis |
| `HOMEKIT_PIN` | zufällig | fester Setup-Code `ddd-dd-ddd` |
| `HOMEKIT_MAC` | zufällig | feste Bridge-Identität `XX:XX:XX:XX:XX:XX` |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8095` | Web-UI-Bind |
| `PV_ENABLED` | `false` | SolarEdge-PV-Accessories bauen |
| `BACKUP_ENABLED` | `true` | automatisches Tages-Backup der Konfig |
| `BACKUP_RETENTION` | `14` | Anzahl aufbewahrter Tages-Snapshots |

Secrets gehören ausschließlich in `.env` — nie in die SQLite-DB oder in den Code.

## Entwicklung

```bash
pip install -e '.[dev]'       # Abhängigkeiten inkl. Dev-Tools
pytest -q                     # Testsuite ausführen
ruff check --fix src tests    # Linting (muss vor dem Commit sauber sein)
```

Architekturdetails und Konventionen stehen in `CLAUDE.md`.

## Fehlersuche

**Keine Geräte in der Web-UI** — Geräte kommen über MQTT, nicht direkt von der CCU3. Prüfe,
ob der Broker läuft (`make logs` zeigt `mqtt`) und ob der `ccu3`-Dienst auf
`homematic/$discovery` publisht. Zum Verifizieren mitlesen:

```bash
docker exec -it mqtt mosquitto_sub -t 'homematic/#' -v
```

**HomeKit „Keine Antwort"** — HAP-Treiber und Host müssen im selben LAN wie deine
Apple-Geräte sein. Host-Networking prüfen: `docker inspect homekit-bridge | grep NetworkMode`
sollte `host` zeigen. Sicherstellen, dass UDP 51826 nicht geblockt ist.

**Web-UI nicht erreichbar** — Default-Port ist 8095 (`WEB_PORT`); der Dienst bindet
standardmäßig an `0.0.0.0` (`WEB_HOST`).

**PV-Accessory zeigt 0 kWh** — `solaredge/state` enthält kein Tagesenergie-Feld, daher ist
`energy_today_kwh` immer 0. Der Quell-Dienst müsste ein Energie-Feld publishen.

## Lizenz

Dieses Projekt steht unter der **GNU General Public License v3.0 oder später**
(GPL-3.0-or-later). Den vollständigen Lizenztext findest du in der Datei
[LICENSE](LICENSE).
