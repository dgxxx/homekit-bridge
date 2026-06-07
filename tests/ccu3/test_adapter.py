from homekit_bridge.ccu3.adapter import Ccu3Adapter
from homekit_bridge.ccu3.client import Ccu3Error
from homekit_bridge.events import EventBus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self, init_fail=False):
        self.init_calls: list[tuple] = []
        self.set_calls: list[tuple] = []
        self._init_fail = init_fail
        self._fail_count = 0

    def init(self, callback_url: str, interface_id: str) -> None:
        self.init_calls.append((callback_url, interface_id))
        if self._init_fail:
            self._fail_count += 1
            raise Ccu3Error("connection refused")

    def set_value(self, address: str, key: str, value) -> None:
        self.set_calls.append((address, key, value))

    def get_value(self, address: str, key: str):
        return None

    def list_devices(self):
        return []


class FakeCallbackServer:
    def __init__(self):
        self.started = False
        self.on_event = None
        self._url = "http://127.0.0.1:9999"

    @property
    def url(self) -> str:
        return self._url

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def fire(self, address: str, key: str, value) -> None:
        """Test helper — simulates an incoming CCU3 event."""
        if self.on_event:
            self.on_event(address, key, value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_start_calls_client_init():
    client = FakeClient()
    cb = FakeCallbackServer()
    bus = EventBus()
    adapter = Ccu3Adapter(
        client=client,
        callback_server=cb,
        bus=bus,
        sleep=lambda s: None,
    )
    adapter.start()
    assert cb.started
    assert len(client.init_calls) == 1
    url, iface = client.init_calls[0]
    assert url == cb.url


def test_incoming_event_published_to_bus():
    client = FakeClient()
    cb = FakeCallbackServer()
    bus = EventBus()
    received = []
    bus.subscribe("ccu3.state", lambda e: received.append(e))

    adapter = Ccu3Adapter(
        client=client,
        callback_server=cb,
        bus=bus,
        sleep=lambda s: None,
    )
    adapter.start()
    cb.fire("OEQ1:1", "STATE", True)
    assert received == [{"address": "OEQ1:1", "key": "STATE", "value": True}]


def test_set_value_delegates_to_client():
    client = FakeClient()
    bus = EventBus()
    adapter = Ccu3Adapter(
        client=client,
        callback_server=FakeCallbackServer(),
        bus=bus,
        sleep=lambda s: None,
    )
    adapter.start()
    adapter.set_value("OEQ1:1", "STATE", False)
    assert client.set_calls == [("OEQ1:1", "STATE", False)]


def test_init_failure_schedules_retry():
    """Adapter must not raise when init fails; it should schedule a retry."""
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # After first retry, make subsequent init calls succeed
        client._init_fail = False

    client = FakeClient(init_fail=True)
    cb = FakeCallbackServer()
    bus = EventBus()

    adapter = Ccu3Adapter(
        client=client,
        callback_server=cb,
        bus=bus,
        sleep=fake_sleep,
        max_retries=3,
    )
    # start() should survive the first failure and retry until success
    adapter.start()
    # At least one retry sleep must have happened
    assert len(sleep_calls) >= 1
    # init was called more than once (first fail + retry success) -> eventually succeeded
    assert len(client.init_calls) >= 2


def test_reconnect_backoff_is_capped():
    """Backoff delay must not grow unboundedly; it should be capped."""
    sleep_calls: list[float] = []
    attempt = [0]

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        attempt[0] += 1
        if attempt[0] >= 4:
            # Succeed after 4 failures
            client._init_fail = False

    client = FakeClient(init_fail=True)
    bus = EventBus()
    adapter = Ccu3Adapter(
        client=client,
        callback_server=FakeCallbackServer(),
        bus=bus,
        sleep=fake_sleep,
        max_retries=10,
        max_backoff=30.0,
    )
    adapter.start()
    # All sleep values must be <= max_backoff
    assert all(s <= 30.0 for s in sleep_calls), sleep_calls
