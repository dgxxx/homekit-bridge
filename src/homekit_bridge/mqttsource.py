"""MQTT-backed source — drop-in replacement for the CCU3 and SolarEdge adapters.

Presents the Ccu3Adapter interface (``list_devices``/``set_value``/``connected``/``start``)
and feeds the in-process EventBus on the unchanged topics ``ccu3.state`` and
``solaredge.data``, so the rest of the bridge is untouched.
"""

import json
import logging

import paho.mqtt.client as mqtt

from homekit_bridge.events import EventBus
from homekit_bridge.models import Channel, Device, PVData

logger = logging.getLogger(__name__)

_PRODUCING_THRESHOLD_W = 10.0
_STATE_PREFIX = "homematic/"
_STATE_SUFFIX = "/state"
_DISCOVERY_TOPIC = "homematic/$discovery"
_SOLAR_TOPIC = "solaredge/state"


def _build_devices(entries: list[dict]) -> list[Device]:
    """Rekonstruiert Device/Channel aus der flachen $discovery-Liste."""
    devices: dict[str, Device] = {}
    for entry in entries:
        address = entry["address"]
        parent = address.rsplit(":", 1)[0]
        device = devices.get(parent)
        if device is None:
            device = Device(address=parent, model="")
            devices[parent] = device
        device.channels.append(
            Channel(
                address=address,
                hm_type=entry.get("device_type", ""),
                name=entry.get("name", ""),
            )
        )
    return list(devices.values())


class MqttSource:
    def __init__(self, bus: EventBus, host: str = "127.0.0.1", port: int = 1883,
                 client=None) -> None:
        self._bus = bus
        self._host = host
        self._port = port
        self._client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._devices: list[Device] = []
        self._connected = False

    # --- Ccu3Adapter-kompatible Schnittstelle ---------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def list_devices(self) -> list[Device]:
        return list(self._devices)

    def set_value(self, address: str, key: str, value) -> None:
        self._client.publish(f"homematic/{address}/set", json.dumps({key: value}))

    # --- MQTT-Callbacks -------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connected = True
        client.subscribe("homematic/+/state")
        client.subscribe(_DISCOVERY_TOPIC)
        client.subscribe(_SOLAR_TOPIC)
        logger.info("MQTT verbunden — Topics abonniert")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            self.handle(msg.topic, msg.payload.decode("utf-8", "replace"))
        except Exception:
            logger.exception("MQTT-Nachricht fehlgeschlagen: %s", msg.topic)

    # --- testbare Verarbeitung ------------------------------------------------
    def handle(self, topic: str, payload: str) -> None:
        if topic == _DISCOVERY_TOPIC:
            self._devices = _build_devices(json.loads(payload))
        elif topic == _SOLAR_TOPIC:
            self._handle_solar(payload)
        elif topic.startswith(_STATE_PREFIX) and topic.endswith(_STATE_SUFFIX):
            address = topic[len(_STATE_PREFIX):-len(_STATE_SUFFIX)]
            self._handle_ccu3_state(address, payload)

    def _handle_ccu3_state(self, address: str, payload: str) -> None:
        data = json.loads(payload)
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            self._bus.publish(
                "ccu3.state", {"address": address, "key": key, "value": value}
            )

    def _handle_solar(self, payload: str) -> None:
        data = json.loads(payload)
        power_w = float(data.get("power_pv", 0.0) or 0.0)
        pv = PVData(
            power_w=power_w,
            energy_today_kwh=0.0,   # nicht im solaredge/state enthalten
            battery_pct=data.get("battery_soc"),
            producing=power_w > _PRODUCING_THRESHOLD_W,
            available=True,
        )
        self._bus.publish("solaredge.data", pv)
