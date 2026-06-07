import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    web_password: Optional[str] = None
    state_dir: str = "./state"

    @classmethod
    def from_env(cls) -> "Settings":
        port_raw = os.environ.get("MQTT_PORT", "1883")
        try:
            mqtt_port = int(port_raw)
        except ValueError:
            raise ValueError(f"MQTT_PORT must be an integer, got {port_raw!r}") from None
        return cls(
            mqtt_host=os.environ.get("MQTT_HOST", "127.0.0.1"),
            mqtt_port=mqtt_port,
            web_password=os.environ.get("WEB_PASSWORD") or None,
            state_dir=os.environ.get("STATE_DIR", "./state"),
        )
