# MQTT-Broker

[🇬🇧 English](README_mqtt.md) · 🇩🇪 Deutsch

Mosquitto-2.x-Broker für die Heimautomatisierungs-Datendienste. Er läuft als `mqtt`-Service
im Compose-Stack dieses Projekts (`homekit-bridge.yaml`), zusammen mit der Bridge selbst.

## Details

- **Port**: 1883
- **Auth**: anonym (keine Zugangsdaten — nur für das interne LAN gedacht)
- **Persistenz**: aktiviert; Daten in `data/` (gitignored)
- **Konfig**: `config/mosquitto.conf`

## Nutzung

Der Broker startet zusammen mit der Bridge:

```sh
make start                                  # oder:
docker compose -f homekit-bridge.yaml up -d
```

Live-Traffic mitlesen:

```sh
docker exec -it mqtt mosquitto_sub -t '#' -v
```

## Topics

Die Bridge abonniert diese retained Topics (publisht von den externen Quell-Diensten `ccu3`
und `solaredge` — nicht Teil dieses Repos):

| Topic | Beschreibung |
|---|---|
| `homematic/$discovery` | Kanalliste inkl. Raum |
| `homematic/+/state` | Zustand je Kanal |
| `homematic/$sysvar/+/state` | boolesche CCU3-Systemvariablen `{"STATE": bool}` |
| `solaredge/state` | Wechselrichter-Livedaten |

Befehle publisht die Bridge zurück auf:

| Topic | Beschreibung |
|---|---|
| `homematic/<addr>/set` | einen Gerätekanal schalten |
| `homematic/$sysvar/<name>/set` | eine CCU3-Systemvariable umschalten |
