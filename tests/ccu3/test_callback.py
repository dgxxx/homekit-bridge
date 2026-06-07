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
