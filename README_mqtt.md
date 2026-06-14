# MQTT Broker

🇬🇧 English · [🇩🇪 Deutsch](README_mqtt.de.md)

Mosquitto 2.x broker for the home-automation data services. It ships as the `mqtt` service
inside this project's compose stack (`homekit-bridge.yaml`), alongside the bridge itself.

## Details

- **Port**: 1883
- **Auth**: anonymous (no credentials — intended for the internal LAN only)
- **Persistence**: enabled; data stored in `data/` (gitignored)
- **Config**: `config/mosquitto.conf`

## Usage

The broker starts together with the bridge:

```sh
make start                                  # or:
docker compose -f homekit-bridge.yaml up -d
```

Inspect live traffic:

```sh
docker exec -it mqtt mosquitto_sub -t '#' -v
```

## Topics

The bridge subscribes to these retained topics (published by the external `ccu3` and
`solaredge` source services — not part of this repo):

| Topic | Description |
|---|---|
| `homematic/$discovery` | channel list incl. room |
| `homematic/+/state` | per-channel state |
| `homematic/$sysvar/+/state` | boolean CCU3 system variables `{"STATE": bool}` |
| `solaredge/state` | inverter live data |

The bridge publishes commands back to:

| Topic | Description |
|---|---|
| `homematic/<addr>/set` | switch a device channel |
| `homematic/$sysvar/<name>/set` | toggle a CCU3 system variable |
