from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HKType(str, Enum):
    SWITCH = "switch"
    OUTLET = "outlet"
    LIGHTBULB = "lightbulb"
    COVER = "cover"
    THERMOSTAT = "thermostat"
    CONTACT = "contact"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    MOTION = "motion"


@dataclass
class Channel:
    address: str            # CCU3 channel address, e.g. "OEQ0123456:1"
    type: str               # raw HM channel type, e.g. "SWITCH", "BLIND"
    name: str
    exported: bool = False
    hk_type: Optional[HKType] = None  # override; None => auto from `type`


@dataclass
class Device:
    address: str
    model: str
    channels: list[Channel] = field(default_factory=list)


@dataclass
class PVData:
    power_w: float = 0.0
    energy_today_kwh: float = 0.0
    battery_pct: Optional[int] = None
    producing: bool = False
    available: bool = True
