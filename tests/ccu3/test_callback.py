import xmlrpc.client
import time

from homekit_bridge.ccu3.callback import CallbackServer


def test_event_delivered_to_callback():
    received = []

    def on_event(address, key, value):
        received.append((address, key, value))

    server = CallbackServer(on_event=on_event, host="127.0.0.1", port=0)
    server.start()
    try:
        proxy = xmlrpc.client.ServerProxy(server.url)
        proxy.event("iface_id", "OEQ1:1", "STATE", True)
        # Give the server thread a moment to process
        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.01)
        assert received == [("OEQ1:1", "STATE", True)]
    finally:
        server.stop()


def test_housekeeping_methods_do_not_raise():
    server = CallbackServer(on_event=lambda *a: None, host="127.0.0.1", port=0)
    server.start()
    try:
        proxy = xmlrpc.client.ServerProxy(server.url)
        assert proxy.listDevices() == []
        assert proxy.newDevices("iface_id", []) == ""
        assert proxy.deleteDevices("iface_id", []) == ""
        assert proxy.updateDevice("iface_id", "OEQ1", 0) == ""
    finally:
        server.stop()


def test_system_list_methods():
    server = CallbackServer(on_event=lambda *a: None, host="127.0.0.1", port=0)
    server.start()
    try:
        proxy = xmlrpc.client.ServerProxy(server.url)
        methods = proxy.system.listMethods()
        assert "event" in methods
    finally:
        server.stop()


def test_on_event_error_does_not_crash_server():
    """A raising on_event handler must not take down the callback server."""
    call_count = [0]

    def bad_handler(address, key, value):
        call_count[0] += 1
        raise RuntimeError("handler exploded")

    server = CallbackServer(on_event=bad_handler, host="127.0.0.1", port=0)
    server.start()
    try:
        proxy = xmlrpc.client.ServerProxy(server.url)
        # First call raises in on_event — server must still return ""
        result = proxy.event("iface_id", "OEQ1:1", "STATE", True)
        assert result == ""
        # Second call proves the server is still alive
        result = proxy.event("iface_id", "OEQ1:1", "STATE", False)
        assert result == ""
        assert call_count[0] == 2
    finally:
        server.stop()
