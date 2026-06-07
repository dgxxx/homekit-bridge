import logging
import time as _time
from typing import Any, Callable

from homekit_bridge.ccu3.client import Ccu3Client, Ccu3Error
from homekit_bridge.ccu3.callback import CallbackServer
from homekit_bridge.events import EventBus

logger = logging.getLogger(__name__)

_DEFAULT_INTERFACE_ID = "homekit-bridge"
_INITIAL_BACKOFF = 2.0   # seconds for the first retry
_BACKOFF_FACTOR = 2.0    # exponential multiplier


class Ccu3Adapter:
    """Orchestrates the CCU3 client and callback server.

    Responsibilities:
    - Start the callback server and register it with the CCU3 via ``init``.
    - Forward incoming callback events to the EventBus on topic ``"ccu3.state"``.
    - Retry the ``init`` registration with capped exponential backoff on failure.
    - Expose ``set_value`` / ``list_devices`` as the public write interface.

    Inject ``sleep`` and ``max_retries``/``max_backoff`` in tests to avoid real
    delays.
    """

    def __init__(
        self,
        client: Ccu3Client,
        callback_server: CallbackServer,
        bus: EventBus,
        interface_id: str = _DEFAULT_INTERFACE_ID,
        sleep: Callable[[float], None] = _time.sleep,
        max_retries: int = 0,        # 0 = retry indefinitely
        max_backoff: float = 64.0,
    ) -> None:
        self._client = client
        self._callback_server = callback_server
        self._bus = bus
        self._interface_id = interface_id
        self._sleep = sleep
        self._max_retries = max_retries
        self._max_backoff = max_backoff

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the callback server and register with the CCU3."""
        self._callback_server.on_event = self._on_event
        self._callback_server.start()
        self._register_with_backoff()

    def stop(self) -> None:
        self._callback_server.stop()

    def set_value(self, address: str, key: str, value: Any) -> None:
        self._client.set_value(address, key, value)

    def list_devices(self):
        return self._client.list_devices()

    def re_register(self) -> None:
        """Re-register the callback after a CCU3 restart."""
        self._register_with_backoff()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_event(self, address: str, key: str, value: Any) -> None:
        self._bus.publish(
            "ccu3.state",
            {"address": address, "key": key, "value": value},
        )

    def _register_with_backoff(self) -> None:
        """Call client.init(); retry with exponential backoff on failure."""
        backoff = _INITIAL_BACKOFF
        attempt = 0
        while True:
            try:
                self._client.init(self._callback_server.url, self._interface_id)
                return  # success
            except (Ccu3Error, Exception) as exc:
                attempt += 1
                logger.warning(
                    "CCU3 init failed (attempt %d): %s — retrying in %.1fs",
                    attempt,
                    exc,
                    backoff,
                )
                if self._max_retries and attempt >= self._max_retries:
                    logger.error("CCU3 init giving up after %d attempts", attempt)
                    raise
                self._sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, self._max_backoff)
