import logging
import threading
from typing import Callable
from xmlrpc.server import SimpleXMLRPCServer

logger = logging.getLogger(__name__)


class CallbackServer:
    """XML-RPC callback server that receives events pushed by the CCU3.

    Runs in a background daemon thread.  Bind to ``port=0`` in tests to let
    the OS choose a free port; read the actual port back via ``.url``.
    """

    def __init__(
        self,
        on_event: Callable[[str, str, object], None],
        host: str = "0.0.0.0",
        port: int = 9292,
    ) -> None:
        self._on_event = on_event
        self._host = host
        self._port = port
        self._server: SimpleXMLRPCServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("CallbackServer.url accessed before start()")
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._server = SimpleXMLRPCServer(
            (self._host, self._port),
            logRequests=False,
            allow_none=True,
        )
        # Register all methods the CCU3 may call
        self._server.register_function(self._event, "event")
        self._server.register_function(self._list_devices, "listDevices")
        self._server.register_function(self._new_devices, "newDevices")
        self._server.register_function(self._delete_devices, "deleteDevices")
        self._server.register_function(self._update_device, "updateDevice")
        self._server.register_introspection_functions()

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="ccu3-callback",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # ------------------------------------------------------------------
    # XML-RPC handlers
    # ------------------------------------------------------------------

    def _event(self, interface_id: str, address: str, key: str, value: object) -> str:
        try:
            self._on_event(address, key, value)
        except Exception:
            logger.exception("Error in on_event callback for %s/%s", address, key)
        return ""

    def _list_devices(self) -> list:
        return []

    def _new_devices(self, interface_id: str, device_descriptions: list) -> str:
        return ""

    def _delete_devices(self, interface_id: str, addresses: list) -> str:
        return ""

    def _update_device(self, interface_id: str, address: str, hint: int) -> str:
        return ""
