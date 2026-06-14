# MQTT Broker

Mosquitto 2.x MQTT broker for the home-automation data services.

## Details

- **Port**: 1883
- **Auth**: Anonymous (no credentials required on the internal network)
- **Persistence**: Enabled; data stored in `data/` (gitignored)

## Usage

```sh
docker compose --file mqtt.yaml --project-name mqtt up -d
```

## Topic convention

Topics follow the design spec pattern:

```
<source>/<device-or-sensor>/<measurement>
```

Examples:
- `solaredge/inverter/power_w`
- `shelly/plug-kitchen/energy_kwh`
- `gaszaehler/main/volume_m3`

All automation poller services publish to this broker; consumers subscribe to the relevant topics.
