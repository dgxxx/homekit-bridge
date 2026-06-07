"""homekit-bridge entrypoint.

Run as: ``python -m homekit_bridge``

``build(fakes=None)`` assembles all subsystems from env-var settings and
returns an ``AppComponents`` dataclass.  Pass ``fakes`` in tests to inject
mock clients so no real network connections are made.

``main()`` calls ``build()``, starts all background threads, launches
Uvicorn for the web UI, logs the HAP pairing PIN/QR code, and installs a
SIGTERM handler for graceful shutdown.
"""

import logging
import os
import pathlib
import signal
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from pyhap.accessory_driver import AccessoryDriver

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.hap.bridge import HomeKitBridge
from homekit_bridge.models import PVData
from homekit_bridge.mqttsource import MqttSource
from homekit_bridge.settings import Settings
from homekit_bridge.web.api import create_app

logger = logging.getLogger(__name__)

_HAP_PORT = 51826
_WEB_PORT = 8095


# ---------------------------------------------------------------------------
# Shared solar state — written by the poll thread, read by the API
# ---------------------------------------------------------------------------

class _SolarState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pv = PVData()

    @property
    def pv(self) -> PVData:
        with self._lock:
            return self._pv

    @pv.setter
    def pv(self, value: PVData) -> None:
        with self._lock:
            self._pv = value


# ---------------------------------------------------------------------------
# Bridge connectivity / pairing state for /api/status
# ---------------------------------------------------------------------------

class _BridgeState:
    def __init__(
        self,
        hap_driver: Optional[AccessoryDriver] = None,
        ccu3_adapter: Optional[Any] = None,
    ) -> None:
        self.hap_driver = hap_driver
        self.ccu3_adapter = ccu3_adapter
        self.accessory_count: int = 0
        self.solaredge_connected: bool = False

    @property
    def paired(self) -> bool:
        """Live HomeKit pairing state, read from the HAP driver.

        HAP-python tracks paired clients in ``driver.state.paired``; reading it
        here means /api/status reflects reality instead of a stale flag.
        """
        if self.hap_driver is None:
            return False
        try:
            return bool(self.hap_driver.state.paired)
        except Exception:
            return False

    @property
    def ccu3_connected(self) -> bool:
        """Live CCU3 connection state, read from the adapter's init status."""
        if self.ccu3_adapter is None:
            return False
        try:
            return bool(self.ccu3_adapter.connected)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class AppComponents:
    app: Any                        # FastAPI ASGI app
    config_store: ConfigStore
    bus: EventBus
    settings: Settings
    hap_bridge: HomeKitBridge
    hap_driver: AccessoryDriver
    ccu3_adapter: Any
    solar_state: _SolarState
    bridge_state: _BridgeState
    stop_event: threading.Event = field(default_factory=threading.Event)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build(fakes: Optional[dict[str, Any]] = None) -> AppComponents:
    """Assemble all subsystems.  Inject *fakes* to avoid real I/O in tests."""
    fakes = fakes or {}

    settings = Settings.from_env()

    # Ensure state directory exists
    state_dir = pathlib.Path(settings.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    db_path = state_dir / "mappings.db"
    hap_persist = str(state_dir / "hap.state")

    # Shared state objects
    bus = EventBus()
    config_store = ConfigStore(db_path)
    solar_state = _SolarState()
    bridge_state = _BridgeState()
    stop_event = threading.Event()

    # MQTT source — replaces the embedded CCU3 + SolarEdge adapters.
    mqtt_client = fakes.get("mqtt_client")
    mqtt_source = MqttSource(
        bus,
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client=mqtt_client,
    )
    ccu3_adapter = mqtt_source  # drop-in: same interface used downstream
    bridge_state.ccu3_adapter = mqtt_source

    # Solar events → shared solar_state for the web API
    def _on_solar(pv: PVData) -> None:
        solar_state.pv = pv
        bridge_state.solaredge_connected = pv.available

    bus.subscribe("solaredge.data", _on_solar)

    # HAP driver — port=0 when fakes are injected (tests), real port otherwise
    hap_port = 0 if fakes else _HAP_PORT
    hap_driver = AccessoryDriver(port=hap_port, persist_file=hap_persist)
    # Let /api/status report the real pairing state from the driver.
    bridge_state.hap_driver = hap_driver

    # Build HAP bridge
    hk_bridge = HomeKitBridge(
        driver=hap_driver,
        config_store=config_store,
        ccu3_adapter=ccu3_adapter,
        bus=bus,
    )
    hk_bridge.build()

    bridge_state.accessory_count = len(hk_bridge.accessories)

    # FastAPI app
    app = create_app(
        config_store=config_store,
        ccu3_adapter=ccu3_adapter,
        solar_state=solar_state,
        bridge_state=bridge_state,
        settings=settings,
    )

    return AppComponents(
        app=app,
        config_store=config_store,
        bus=bus,
        settings=settings,
        hap_bridge=hk_bridge,
        hap_driver=hap_driver,
        ccu3_adapter=ccu3_adapter,
        solar_state=solar_state,
        bridge_state=bridge_state,
        stop_event=stop_event,
    )


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> None:
    """Wire everything, start all threads, and run until SIGTERM/SIGINT."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    components = build()
    stop_event = components.stop_event

    # SIGTERM / SIGINT → set stop_event
    def _shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %d — shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start MQTT (background network loop) — feeds CCU3 + solar events onto the bus
    components.ccu3_adapter.start()

    # Log HAP pairing info
    driver = components.hap_driver
    _log_pairing_info(driver)

    # Start HAP driver in a background thread
    hap_thread = threading.Thread(
        target=driver.start,
        name="hap-driver",
        daemon=True,
    )
    hap_thread.start()

    # Start Uvicorn in a background thread
    import uvicorn

    web_host = os.environ.get("WEB_HOST", "0.0.0.0")
    web_port = int(os.environ.get("WEB_PORT", str(_WEB_PORT)))

    uvicorn_config = uvicorn.Config(
        components.app,
        host=web_host,
        port=web_port,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    web_thread = threading.Thread(
        target=uvicorn_server.run,
        name="uvicorn",
        daemon=True,
    )
    web_thread.start()

    logger.info(
        "HomeKit Bridge running — web UI on http://%s:%d  HAP on port %d",
        web_host, web_port, _HAP_PORT,
    )

    # Block until shutdown signal
    stop_event.wait()

    logger.info("Stopping HAP driver…")
    driver.stop()
    uvicorn_server.should_exit = True
    logger.info("Shutdown complete.")


def _log_pairing_info(driver: AccessoryDriver) -> None:
    """Print the HAP pairing PIN (and QR code if available) to the log."""
    try:
        pin = driver.state.pincode.decode()
        logger.info("HomeKit pairing PIN: %s", pin)
        try:
            import qrcode  # type: ignore[import-untyped]
            qr = qrcode.QRCode()
            qr.add_data(f"X-HM://00{_encode_setup_id(pin)}HOMEKIT-BRIDGE")
            qr.print_ascii(invert=True)
        except ImportError:
            pass  # qrcode package optional
    except Exception:
        logger.debug("Could not read HAP pairing PIN", exc_info=True)


def _encode_setup_id(pin: str) -> str:
    """Minimal numeric encoding for the HAP QR URI (digits only, no dashes)."""
    return pin.replace("-", "")


if __name__ == "__main__":
    main()
