import json

from homekit_bridge.events import EventBus
from homekit_bridge.models import PVData
from homekit_bridge.mqttsource import MqttSource, _build_devices


class _FakeClient:
    def __init__(self):
        self.published = []
        self.subscriptions = []
        self.on_connect = None
        self.on_message = None

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, topic):
        self.subscriptions.append(topic)


def _src():
    bus = EventBus()
    events = []
    bus.subscribe("ccu3.state", lambda e: events.append(("ccu3", e)))
    bus.subscribe("solaredge.data", lambda e: events.append(("solar", e)))
    src = MqttSource(bus, client=_FakeClient())
    return src, events


def test_ccu3_state_fans_out_per_key():
    src, events = _src()
    src.handle("homematic/ABC:1/state", '{"STATE": true, "LEVEL": 0.5}')
    ccu3 = [e for kind, e in events if kind == "ccu3"]
    assert {"address": "ABC:1", "key": "STATE", "value": True} in ccu3
    assert {"address": "ABC:1", "key": "LEVEL", "value": 0.5} in ccu3


def test_solar_state_maps_to_pvdata():
    src, events = _src()
    src.handle("solaredge/state", '{"power_pv": 2500, "battery_soc": 80}')
    solar = [e for kind, e in events if kind == "solar"]
    assert len(solar) == 1
    pv = solar[0]
    assert isinstance(pv, PVData)
    assert pv.power_w == 2500.0
    assert pv.battery_pct == 80
    assert pv.producing is True
    assert pv.available is True
    assert pv.energy_today_kwh == 0.0


def test_solar_zero_power_not_producing():
    src, events = _src()
    src.handle("solaredge/state", '{"power_pv": 0, "battery_soc": 50}')
    pv = [e for kind, e in events if kind == "solar"][0]
    assert pv.producing is False


def test_set_value_publishes_command():
    src, _ = _src()
    src.set_value("ABC:1", "STATE", True)
    topic, payload, retain = src._client.published[0]
    assert topic == "homematic/ABC:1/set"
    assert json.loads(payload) == {"STATE": True}


def test_discovery_builds_devices_grouped_by_parent():
    src, _ = _src()
    src.handle("homematic/$discovery", json.dumps([
        {"address": "ABC:1", "name": "Schalter", "device_type": "SWITCH"},
        {"address": "ABC:2", "name": "Schalter 2", "device_type": "SWITCH"},
        {"address": "XYZ:1", "name": "Rollo", "device_type": "BLIND"},
    ]))
    devs = {d.address: d for d in src.list_devices()}
    assert set(devs) == {"ABC", "XYZ"}
    abc_channels = {c.address: c for c in devs["ABC"].channels}
    assert abc_channels["ABC:1"].hm_type == "SWITCH"
    assert abc_channels["ABC:1"].name == "Schalter"
    assert len(devs["ABC"].channels) == 2


def test_build_devices_handles_channel_without_colon():
    devs = _build_devices([{"address": "ABC", "name": "n", "device_type": "T"}])
    assert devs[0].address == "ABC"
    assert devs[0].channels[0].address == "ABC"


def test_discovery_parses_room_per_channel():
    src, _ = _src()
    src.handle("homematic/$discovery", json.dumps([
        {"address": "ABC:1", "name": "Schalter", "device_type": "SWITCH",
         "room": "Wohnzimmer"},
        {"address": "XYZ:1", "name": "Rollo", "device_type": "BLIND"},
    ]))
    devs = {d.address: d for d in src.list_devices()}
    assert devs["ABC"].channels[0].room == "Wohnzimmer"
    # Missing room field defaults to empty string
    assert devs["XYZ"].channels[0].room == ""


def test_connected_reflects_on_connect():
    src, _ = _src()
    assert src.connected is False
    src._on_connect(src._client, None, None, 0, None)
    assert src.connected is True
    assert "homematic/+/state" in src._client.subscriptions
    assert "homematic/$discovery" in src._client.subscriptions
    assert "solaredge/state" in src._client.subscriptions
