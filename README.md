# HomeKit Bridge

🇬🇧 English · [🇩🇪 Deutsch](README.de.md)

A Dockerized Python service that exposes **Homematic CCU3** devices (read + switch) and
**SolarEdge PV** live data (read-only) as native HomeKit accessories — configurable through
a small Vanilla-JS web UI. It replaces the HomeKit add-on of the CCU3.

## Architecture

The bridge is an **MQTT consumer**. It does *not* talk to the CCU3 or the inverter
directly. Two separate source services publish device data to an MQTT broker, and the
bridge subscribes to it:

```
  ccu3 service ─┐
                ├─▶  MQTT broker (1883)  ◀──  homekit-bridge  ──▶  Apple Home
  solaredge ────┘                                   │
                                                     └──▶  Browser (config web UI)
```

Topics consumed (all retained):

| Topic | Published by | Payload |
|---|---|---|
| `homematic/$discovery` | ccu3 | channel list incl. room |
| `homematic/+/state` | ccu3 | per-channel state |
| `homematic/$sysvar/+/state` | ccu3 | boolean CCU3 system variables `{"STATE": bool}` |
| `solaredge/state` | solaredge | inverter live data |

The bridge publishes back to `homematic/<addr>/set` (and `homematic/$sysvar/<name>/set`)
to switch devices.

> The `ccu3` and `solaredge` source services are **not** part of this repo. This repo
> contains the bridge plus a ready-to-run Mosquitto broker (see
> [README_mqtt.md](README_mqtt.md)).

## Requirements

- Docker + Docker Compose on a Linux host
- An MQTT broker (bundled — see the compose stack below)
- The `ccu3` / `solaredge` source services publishing to that broker (for live data)
- `network_mode: host` — required so HomeKit's mDNS/Bonjour discovery reaches the LAN and
  so the bridge can reach the broker at `127.0.0.1:1883`

## Setup

1. **Clone** the repo onto your server.

2. **Create your `.env`** from the example:

   ```bash
   cp .env.example .env
   ```

   All values have sane defaults; for a local broker on the same host nothing *must* be
   changed. Common overrides:

   ```
   MQTT_HOST=127.0.0.1      # broker address (default)
   MQTT_PORT=1883           # broker port (default)
   WEB_PASSWORD=...          # optional HTTP-Basic password for the web UI
   HOMEKIT_PIN=123-45-678    # optional fixed pairing code (see .env.example)
   ```

3. **Start the stack** (bridge + Mosquitto broker). The active compose file is
   `homekit-bridge.yaml`; the bundled `make` targets wrap it:

   ```bash
   make start          # = docker compose -f homekit-bridge.yaml up -d
   make buildstart     # rebuild the image, then start
   make logs           # follow the bridge logs
   make restart
   make stop
   ```

   Or call Compose directly:

   ```bash
   docker compose -f homekit-bridge.yaml up -d
   ```

   On first start the image is built and `./state/` (SQLite DB + HAP pairing) and
   `./data/` (broker persistence) are created.

4. **Open the web UI** at `http://<server-ip>:8095`.

## HomeKit pairing

1. Find the setup code in the logs:

   ```bash
   make logs            # or: docker compose -f homekit-bridge.yaml logs homekit-bridge
   ```

   Without `HOMEKIT_PIN` the code is **regenerated on every restart** (pyhap does not
   persist it). Set `HOMEKIT_PIN` in `.env` to keep it stable — see `.env.example`.

2. On your iPhone/iPad: **Home → + → Add Accessory → More options**, then scan the QR code
   (shown in the web UI / logs) or enter the PIN manually.

3. Once paired, every exported device appears as a HomeKit accessory under the single
   bridge — no per-device pairing.

## Mapping devices in the web UI

1. Open the **Geräte** tab — all channels discovered from MQTT are listed, grouped by room.
2. Toggle **Export** to expose a channel to HomeKit.
3. Pick the **HomeKit type** (Switch, Lightbulb, Cover, Contact/Window/Door, …). A sensible
   default is pre-selected from the CCU3 channel type.
4. Set the **Name** shown in the Home app.
5. **Save** — accessories are reconciled live; no restart needed.

A few type notes:

- **Window/door contacts:** export as `contact` (sensor — appears only in the status row),
  or as `window`/`door` for a full room tile (positional service, read-only).
- **CCU3 system variables** (boolean sysvars released by the `ccu3` service) show up under
  the room *"System-Variablen"* and can be exported as Switch (default) or a read-only
  sensor type.
- **PV/solar accessories** are **off by default** (`PV_ENABLED=false`) — HomeKit has no
  native watt/kWh characteristic, so the stock Home app renders them confusingly. PV data
  is always visible in the web UI regardless.

## Configuration backup / restore

The full config (device mappings + HomeKit accessory IDs) can be backed up and restored as
JSON:

- **Automatic:** one daily snapshot into `STATE_DIR/backups`, rotated (`BACKUP_ENABLED`,
  `BACKUP_RETENTION` — see `.env.example`).
- **Manual:** web UI tab **"Sicherung"** — download a backup, restore an upload, or load an
  auto-backup. The HomeKit accessory IDs are included, so a restore reproduces the same
  accessory DB **without re-pairing**.

## Persistent state

| Path | Contents |
|---|---|
| `state/mappings.db` | SQLite: device → HomeKit type / name / export flag + accessory IDs |
| `state/hap.state` | HAP pairing keys — **deleting this breaks the pairing** |
| `state/backups/` | rotated daily config snapshots |
| `data/` | Mosquitto broker persistence |

Back up `./state/` to avoid losing pairings. (All four paths are gitignored.)

## Environment variables

See [.env.example](.env.example) for the full, commented list. Summary:

| Variable | Default | Purpose |
|---|---|---|
| `MQTT_HOST` | `127.0.0.1` | broker host |
| `MQTT_PORT` | `1883` | broker port |
| `WEB_PASSWORD` | — | optional web-UI password (HTTP Basic) |
| `STATE_DIR` | `./state` (`/app/state` in Docker) | persistent data dir |
| `HOMEKIT_PIN` | random | fixed setup code `ddd-dd-ddd` |
| `HOMEKIT_MAC` | random | fixed bridge identity `XX:XX:XX:XX:XX:XX` |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8095` | web UI bind |
| `PV_ENABLED` | `false` | build SolarEdge PV accessories |
| `BACKUP_ENABLED` | `true` | automatic daily config backup |
| `BACKUP_RETENTION` | `14` | daily snapshots to keep |

Secrets live in `.env` only — never in the SQLite DB or in code.

## Development

```bash
pip install -e '.[dev]'       # deps incl. dev tools
pytest -q                     # run the test suite
ruff check --fix src tests    # lint (must be clean before committing)
```

See `CLAUDE.md` for architecture details and conventions.

## Troubleshooting

**No devices in the web UI** — devices come from MQTT, not the CCU3 directly. Check that
the broker is up (`make logs` shows `mqtt`) and that the `ccu3` service is publishing to
`homematic/$discovery`. Subscribe to verify:

```bash
docker exec -it mqtt mosquitto_sub -t 'homematic/#' -v
```

**HomeKit "No Response"** — the HAP driver and host must be on the same LAN as your Apple
devices. Confirm host networking: `docker inspect homekit-bridge | grep NetworkMode`
should show `host`. Ensure UDP 51826 isn't firewalled.

**Web UI not reachable** — default port is 8095 (`WEB_PORT`); the service binds `0.0.0.0`
(`WEB_HOST`) by default.

**PV accessory shows 0 kWh** — `solaredge/state` carries no daily-energy field, so
`energy_today_kwh` is always 0. The source service would need to publish an energy field.
