# HomeKit Bridge

A Dockerized Python service that exposes Homematic CCU3 devices and SolarEdge PV live data as HomeKit accessories, configurable via a web UI.

## What it does

- Reads and controls Homematic CCU3 devices (switches, dimmers, blinds, sensors, thermostats) over XML-RPC
- Reads SolarEdge inverter live data (AC power, today's energy, battery SoC) over Modbus TCP
- Exposes everything as HomeKit accessories via a single HAP bridge (one pairing)
- Provides a web UI for mapping/naming devices and viewing status

## Requirements

- Docker and Docker Compose on a Linux host
- Homematic CCU3 reachable on the LAN with XML-RPC enabled (default port 2001)
- SolarEdge inverter with Modbus TCP enabled on port 1502
- The host must be on the same network as the CCU3 and SolarEdge
- `network_mode: host` is required for HAP mDNS/Bonjour and for the CCU3 callback server

## Setup

1. **Clone / copy** the project to your server.

2. **Create your `.env`** from the example:

   ```bash
   cp .env.example .env
   ```

   Fill in at minimum:

   ```
   CCU3_HOST=192.168.1.10        # your CCU3 IP
   SOLAREDGE_HOST=192.168.1.20   # your inverter IP
   ```

3. **Start the service:**

   ```bash
   docker compose up -d
   ```

   On first start Docker builds the image and creates the `./state/` directory for persistent data.

4. **Open the web UI** at `http://<server-ip>:8095`

## HomeKit Pairing

1. After startup, look for the pairing PIN in the container logs:

   ```bash
   docker compose logs homekit-bridge | grep "pairing PIN"
   ```

2. On your iPhone/iPad, open **Home** → **+** → **Add Accessory** → **More options** and scan the QR code (if shown) or enter the PIN manually.

3. Once paired, all exported devices appear as HomeKit accessories.

## Mapping devices in the web UI

1. Go to the **Geräte** tab.
2. Devices discovered from the CCU3 are listed.
3. Toggle **Export** to expose a device to HomeKit.
4. Set the **HomeKit type** (Switch, Lightbulb, Cover, etc.) — auto-detected from the CCU3 channel type if left blank.
5. Set a **Name** as it should appear in the Home app.
6. Click **Save**.

Changes take effect after restarting the service (so the HAP bridge re-registers the accessories).

## Host network requirement

`network_mode: host` is mandatory because:

- **HAP/mDNS**: HomeKit discovery relies on multicast DNS (Bonjour). Bridge networking prevents mDNS from reaching the LAN.
- **CCU3 callback**: The CCU3 pushes state changes to the callback server by connecting back to the container. With bridge networking the container IP is not reachable from the CCU3.

## Persistent state

Everything in `./state/` is persistent:

| File | Contents |
|---|---|
| `state/mappings.db` | SQLite: device → HomeKit type / name / export flag |
| `state/hap.state` | HAP pairing keys (deleting this breaks the pairing) |

Back up `./state/` to avoid losing pairings.

## Troubleshooting

### CCU3 devices not appearing

- Verify the CCU3 XML-RPC interface is enabled: CCU3 web UI → Settings → Interfaces.
- Check `CCU3_HOST` in `.env`.
- The callback server listens on port 9292; ensure nothing else uses that port.

### CCU3 stops pushing updates after a CCU3 restart

The CCU3 loses callback registrations on restart. The bridge will automatically re-register (exponential backoff, up to 64 s). Watch the logs:

```bash
docker compose logs -f homekit-bridge | grep ccu3
```

If it stays stuck, restart the bridge:

```bash
docker compose restart homekit-bridge
```

### SolarEdge not showing data

- Verify Modbus TCP is enabled on the inverter: inverter display → Communication → RS485 / Modbus.
- Default port is 1502, unit ID 1. Adjust `SOLAREDGE_UNIT_ID` in `.env` if needed.
- The register map was written for SunSpec-compliant SE-series inverters. Check logs for "SolarEdge read failed" and note the register address for model-specific adjustments.

### HomeKit "No Response"

- The HAP driver must be running and the host must be on the same network as your Apple devices.
- Check that port 51826/UDP is not blocked by a local firewall.
- Verify that `network_mode: host` is active: `docker inspect homekit-bridge | grep NetworkMode`.

### Web UI not reachable

- Default port is 8095. Override with `WEB_PORT=<port>` in `.env`.
- The service binds to `0.0.0.0` by default; set `WEB_HOST` in `.env` to restrict.
