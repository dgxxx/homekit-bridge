import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    ccu3_host: str
    solaredge_host: str
    solaredge_unit_id: int = 1
    web_password: Optional[str] = None
    state_dir: str = "./state"

    @classmethod
    def from_env(cls) -> "Settings":
        ccu3_host = os.environ.get("CCU3_HOST")
        if not ccu3_host:
            raise ValueError("CCU3_HOST environment variable is required")

        solaredge_host = os.environ.get("SOLAREDGE_HOST")
        if not solaredge_host:
            raise ValueError("SOLAREDGE_HOST environment variable is required")

        unit_id_raw = os.environ.get("SOLAREDGE_UNIT_ID", "1")
        try:
            solaredge_unit_id = int(unit_id_raw)
        except ValueError:
            raise ValueError(
                f"SOLAREDGE_UNIT_ID must be an integer, got {unit_id_raw!r}"
            ) from None

        web_password = os.environ.get("WEB_PASSWORD") or None
        state_dir = os.environ.get("STATE_DIR", "./state")

        return cls(
            ccu3_host=ccu3_host,
            solaredge_host=solaredge_host,
            solaredge_unit_id=solaredge_unit_id,
            web_password=web_password,
            state_dir=state_dir,
        )
