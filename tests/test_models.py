from homekit_bridge.models import Channel, PVData


def test_channel_defaults():
    ch = Channel(address="ABC123:1", hm_type="SWITCH", name="Lamp")
    assert ch.exported is False
    assert ch.hk_type is None


def test_pvdata_holds_values():
    pv = PVData(power_w=2450.0, energy_today_kwh=14.2, battery_pct=78, producing=True)
    assert pv.producing and pv.power_w == 2450.0
