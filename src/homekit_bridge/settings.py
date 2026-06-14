import os
import re
from dataclasses import dataclass
from typing import Optional

# HomeKit setup code: 8 digits formatted as ddd-dd-ddd.
_PIN_RE = re.compile(r"^\d{3}-\d{2}-\d{3}$")


@dataclass
class Settings:
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    web_password: Optional[str] = None
    state_dir: str = "./state"
    # Optional fixed HomeKit pairing identity. pyhap does NOT persist the
    # pincode, so without these the setup code is regenerated on every restart.
    # Setting them keeps the setup code stable and preserves the bridge identity
    # even if hap.state is lost. Both None => pyhap generates random values.
    homekit_pin: Optional[str] = None
    homekit_mac: Optional[str] = None
    # PV/solar accessories are off by default: HomeKit has no native watt/kWh
    # characteristic, so the stock Home app shows them in a confusing way.
    pv_enabled: bool = False
    # Automatic daily config backup into STATE_DIR/backups. On by default;
    # disable with BACKUP_ENABLED=false. backup_retention = how many daily
    # snapshots to keep (older ones are pruned).
    backup_enabled: bool = True
    backup_retention: int = 14

    @classmethod
    def from_env(cls) -> "Settings":
        port_raw = os.environ.get("MQTT_PORT", "1883")
        try:
            mqtt_port = int(port_raw)
        except ValueError:
            raise ValueError(f"MQTT_PORT must be an integer, got {port_raw!r}") from None

        homekit_pin = os.environ.get("HOMEKIT_PIN") or None
        if homekit_pin is not None and not _PIN_RE.match(homekit_pin):
            raise ValueError(
                f"HOMEKIT_PIN must look like 123-45-678, got {homekit_pin!r}"
            )

        pv_enabled = os.environ.get("PV_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

        # On by default — only an explicit falsy value turns auto-backup off.
        backup_enabled = os.environ.get("BACKUP_ENABLED", "").strip().lower() not in {
            "0", "false", "no", "off",
        }

        retention_raw = os.environ.get("BACKUP_RETENTION", "14").strip() or "14"
        try:
            backup_retention = int(retention_raw)
        except ValueError:
            raise ValueError(
                f"BACKUP_RETENTION must be an integer, got {retention_raw!r}"
            ) from None
        if backup_retention < 1:
            backup_retention = 1

        return cls(
            mqtt_host=os.environ.get("MQTT_HOST", "127.0.0.1"),
            mqtt_port=mqtt_port,
            web_password=os.environ.get("WEB_PASSWORD") or None,
            state_dir=os.environ.get("STATE_DIR", "./state"),
            homekit_pin=homekit_pin,
            homekit_mac=os.environ.get("HOMEKIT_MAC") or None,
            pv_enabled=pv_enabled,
            backup_enabled=backup_enabled,
            backup_retention=backup_retention,
        )
