"""HomeKit bridge wiring layer.

``HomeKitBridge`` builds a single ``pyhap.accessory.Bridge`` accessory,
populates it from the config store, and wires bidirectional state flow:

- HomeKit SET  →  ``on_set`` callback  →  ``ccu3_adapter.set_value``
- EventBus ``"ccu3.state"``    →  matching accessory's ``update_state``
- EventBus ``"solaredge.data"``  →  PV accessory group's ``update_state``
"""

import logging
from typing import Any, Optional

from pyhap.accessory import Accessory, Bridge as HAPBridge
from pyhap.accessory_driver import AccessoryDriver

from homekit_bridge.config import ConfigStore
from homekit_bridge.events import EventBus
from homekit_bridge.hap.accessories import (
    BatteryAccessory,
    EvePowerAccessory,
    LightSensorAccessory,
    ProducingAccessory,
    make_accessory,
)
from homekit_bridge.mapper.datapoints import WRITE_DATAPOINTS, read_update
from homekit_bridge.mapper.device_mapper import resolve_hk_type
from homekit_bridge.models import HKType, PVData

logger = logging.getLogger(__name__)


class HomeKitBridge:
    """Builds and manages the single HAP bridge presented to HomeKit.

    One bridge == one pairing code; all accessories live under it.
    """

    def __init__(
        self,
        driver: AccessoryDriver,
        config_store: ConfigStore,
        ccu3_adapter: Any,
        bus: EventBus,
    ) -> None:
        self._driver = driver
        self._store = config_store
        self._ccu3 = ccu3_adapter
        self._bus = bus

        self.hap_bridge: Optional[HAPBridge] = None
        # address -> accessory, for fast lookup on incoming events
        self._addr_index: dict[str, Accessory] = {}
        # address -> the exported mapping used to build the accessory (change detection)
        self._exported: dict[str, dict] = {}
        # PV accessory group: kind -> accessory
        self.pv_accessories: dict[str, Accessory] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def accessories(self) -> list[Accessory]:
        """All CCU3 accessories added to the bridge (excludes PV group)."""
        return list(self._addr_index.values())

    def build(self) -> HAPBridge:
        """Instantiate the HAP bridge, populate accessories, subscribe to events."""
        self.hap_bridge = HAPBridge(self._driver, "HomeKit Bridge")

        self._build_ccu3_accessories()
        self._build_pv_accessories()

        # Register the bridge with the driver so it can be started/paired.
        self._driver.add_accessory(self.hap_bridge)

        self._bus.subscribe("ccu3.state", self._on_ccu3_state)
        self._bus.subscribe("solaredge.data", self._on_solaredge_data)
        self._bus.subscribe("config.changed", self.reconcile)

        return self.hap_bridge

    # ------------------------------------------------------------------
    # Build helpers
    # ------------------------------------------------------------------

    def _wire_writables(self, acc, address: str, hk_type: HKType) -> None:
        get_chars = getattr(acc, "writable_characteristics", None)
        if get_chars is None:
            return
        chars = get_chars()
        for semantic, dp in WRITE_DATAPOINTS.get(hk_type, {}).items():
            char = chars.get(semantic)
            if char is None:
                continue

            def setter(value, addr=address, key=dp.kwarg, scale=dp.scale):
                try:
                    self._ccu3.set_value(
                        addr, key, value / scale if scale != 1.0 else value
                    )
                except Exception:
                    logger.exception("set_value failed for %s", addr)

            char.setter_callback = setter

    def _make_ccu3_accessory(self, mapping: dict) -> Optional[Accessory]:
        address = mapping["address"]
        name = mapping["name"] or address
        hk_type = resolve_hk_type(_ChannelProxy(address=address, hm_type=""), mapping)
        if hk_type is None:
            logger.info("Skipping %s: no HKType resolved", address)
            return None
        acc = make_accessory(driver=self._driver, hk_type=hk_type.value, name=name)
        self._wire_writables(acc, address, hk_type)
        return acc

    def _build_ccu3_accessories(self) -> None:
        for mapping in self._store.list_exported():
            address: str = mapping["address"]
            try:
                acc = self._make_ccu3_accessory(mapping)
            except Exception:
                logger.exception("Failed to build accessory for %s", address)
                continue
            if acc is None:
                continue
            self.hap_bridge.add_accessory(acc)
            self._addr_index[address] = acc
            self._exported[address] = mapping

    def _build_pv_accessories(self) -> None:
        drv = self._driver
        self.pv_accessories = {
            "light_sensor": LightSensorAccessory(drv, "PV Power (lux)"),
            "eve_power": EvePowerAccessory(drv, "PV Energy"),
            "battery": BatteryAccessory(drv, "PV Battery"),
            "producing": ProducingAccessory(drv, "PV Producing"),
        }
        for acc in self.pv_accessories.values():
            self.hap_bridge.add_accessory(acc)

    def reconcile(self, _event: Any = None) -> None:
        """Schedule a reconcile of exported mappings against live accessories.

        Reads the desired exported set here (caller/bus thread; SQLite is
        lock-protected) and marshals the diff + mutation onto the driver event
        loop, which is the single owner of ``self._exported`` / ``self._addr_index``
        and of the HAP ``accessories`` dict — so there are no cross-thread races on
        the bridge's bookkeeping.

        The event's ``address`` is intentionally ignored: a full-set reconcile is
        idempotent and self-healing (it also recovers any update missed earlier).
        """
        desired = {m["address"]: m for m in self._store.list_exported()}
        self._driver.loop.call_soon_threadsafe(self._apply, desired)

    def _apply(self, desired: dict[str, dict]) -> None:
        """Diff *desired* against live accessories and mutate the HAP bridge.

        Runs on the driver event loop (sole owner of the bookkeeping dicts and the
        HAP ``accessories`` dict). Reacts to export (add), un-export (remove) and
        hk_type change (replace). Name-only changes are intentionally ignored so
        HomeKit's per-AID room/name assignment is preserved (see design doc).
        """
        to_add: list[dict] = []
        to_remove: list[str] = []
        for addr, m in desired.items():
            cur = self._exported.get(addr)
            if cur is None:
                to_add.append(m)
            elif cur.get("hk_type") != m.get("hk_type"):
                to_remove.append(addr)
                to_add.append(m)
        for addr in list(self._exported):
            if addr not in desired:
                to_remove.append(addr)

        changed = False
        for addr in to_remove:
            acc = self._addr_index.pop(addr, None)
            self._exported.pop(addr, None)
            if acc is not None and acc.aid in self.hap_bridge.accessories:
                del self.hap_bridge.accessories[acc.aid]
                changed = True
        for mapping in to_add:
            address = mapping["address"]
            try:
                acc = self._make_ccu3_accessory(mapping)
            except Exception:
                logger.exception("Failed to build accessory for %s", address)
                continue
            if acc is None:
                continue
            self.hap_bridge.add_accessory(acc)
            self._addr_index[address] = acc
            self._exported[address] = mapping
            changed = True
        if changed:
            self._driver.config_changed()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_ccu3_state(self, event: dict) -> None:
        address: str = event.get("address", "")
        acc = self._addr_index.get(address)
        mapping = self._exported.get(address)
        if acc is None or mapping is None:
            return
        upd = read_update(mapping["hk_type"], event.get("key"), event.get("value"))
        if not upd:
            return
        try:
            acc.update_state(**upd)
        except Exception:
            logger.exception("update_state failed for %s", address)

    def _on_solaredge_data(self, pv: PVData) -> None:
        try:
            self.pv_accessories["light_sensor"].update_state(lux=pv.power_w)
            self.pv_accessories["eve_power"].update_state(watts=pv.power_w, kwh=pv.energy_today_kwh)
            self.pv_accessories["battery"].update_state(pct=pv.battery_pct)
            self.pv_accessories["producing"].update_state(on=pv.producing)
        except Exception:
            logger.exception("PV accessory update failed")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _ChannelProxy:
    """Minimal duck-type satisfying resolve_hk_type's channel parameter."""

    def __init__(self, address: str, hm_type: str) -> None:
        self.address = address
        self.hm_type = hm_type
        self.hk_type = None
