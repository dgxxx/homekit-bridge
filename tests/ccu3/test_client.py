import pytest
from homekit_bridge.ccu3.client import Ccu3Client, Ccu3Error


class FakeProxy:
    def __init__(self):
        self.calls = []

    def setValue(self, address, key, value):
        self.calls.append(("set", address, key, value))

    def getValue(self, address, key):
        return "ON"

    def listDevices(self):
        return [
            {"ADDRESS": "OEQ1", "TYPE": "HM-LC-Sw1", "CHILDREN": ["OEQ1:1"]},
            {"ADDRESS": "OEQ1:1", "TYPE": "SWITCH", "PARENT": "OEQ1"},
        ]


def test_set_and_get():
    p = FakeProxy()
    c = Ccu3Client(proxy=p)
    c.set_value("OEQ1:1", "STATE", True)
    assert p.calls == [("set", "OEQ1:1", "STATE", True)]
    assert c.get_value("OEQ1:1", "STATE") == "ON"


def test_list_devices_builds_channels():
    c = Ccu3Client(proxy=FakeProxy())
    devices = c.list_devices()
    chans = [ch for d in devices for ch in d.channels]
    assert any(ch.address == "OEQ1:1" and ch.type == "SWITCH" for ch in chans)


def test_list_devices_groups_channels_under_parent():
    c = Ccu3Client(proxy=FakeProxy())
    devices = c.list_devices()
    # The device OEQ1 should have OEQ1:1 as a channel
    dev = next((d for d in devices if d.address == "OEQ1"), None)
    assert dev is not None
    assert any(ch.address == "OEQ1:1" for ch in dev.channels)


def test_set_value_wraps_exception():
    class BrokenProxy:
        def setValue(self, *a):
            raise ConnectionError("boom")

    c = Ccu3Client(proxy=BrokenProxy())
    with pytest.raises(Ccu3Error):
        c.set_value("OEQ1:1", "STATE", True)


def test_get_value_wraps_exception():
    class BrokenProxy:
        def getValue(self, *a):
            raise ConnectionError("boom")

    c = Ccu3Client(proxy=BrokenProxy())
    with pytest.raises(Ccu3Error):
        c.get_value("OEQ1:1", "STATE")
