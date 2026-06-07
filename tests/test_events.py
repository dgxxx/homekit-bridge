from homekit_bridge.events import EventBus


def test_subscribe_and_publish():
    bus = EventBus()
    seen = []
    bus.subscribe("state", lambda e: seen.append(e))
    bus.publish("state", {"addr": "X:1", "value": True})
    assert seen == [{"addr": "X:1", "value": True}]


def test_handler_error_does_not_break_bus():
    bus = EventBus()
    ok = []
    bus.subscribe("state", lambda e: (_ for _ in ()).throw(RuntimeError()))
    bus.subscribe("state", lambda e: ok.append(e))
    bus.publish("state", 1)  # must not raise
    assert ok == [1]


def test_multiple_topics_isolated():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("topic_a", lambda e: a.append(e))
    bus.subscribe("topic_b", lambda e: b.append(e))
    bus.publish("topic_a", "hello")
    assert a == ["hello"] and b == []


def test_unsubscribed_topic_does_not_raise():
    bus = EventBus()
    bus.publish("nonexistent", {"key": "value"})  # must not raise
