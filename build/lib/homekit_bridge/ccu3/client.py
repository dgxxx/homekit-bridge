import xmlrpc.client
from typing import Any, Optional

from homekit_bridge.models import Channel, Device


class Ccu3Error(Exception):
    """Raised when the CCU3 XML-RPC call fails."""


class Ccu3Client:
    """Thin wrapper around the CCU3 XML-RPC interface.

    Pass a ``proxy`` in tests to avoid real network calls.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 2001,
        proxy: Any = None,
    ) -> None:
        if proxy is not None:
            self._proxy = proxy
        else:
            self._proxy = xmlrpc.client.ServerProxy(f"http://{host}:{port}")

    def init(self, callback_url: str, interface_id: str) -> None:
        """Register (or, with an empty ``interface_id``, deregister) our XML-RPC
        callback with the CCU3 so it pushes value-change events to us."""
        try:
            self._proxy.init(callback_url, interface_id)
        except Exception as exc:
            raise Ccu3Error(f"init failed for {callback_url}/{interface_id}") from exc

    def set_value(self, address: str, key: str, value: Any) -> None:
        try:
            self._proxy.setValue(address, key, value)
        except Exception as exc:
            raise Ccu3Error(f"setValue failed for {address}/{key}") from exc

    def get_value(self, address: str, key: str) -> Any:
        try:
            return self._proxy.getValue(address, key)
        except Exception as exc:
            raise Ccu3Error(f"getValue failed for {address}/{key}") from exc

    def list_devices(self) -> list[Device]:
        """Fetch all devices from the CCU3 and group channels under their parents."""
        try:
            raw: list[dict] = self._proxy.listDevices()
        except Exception as exc:
            raise Ccu3Error("listDevices failed") from exc

        # Separate root devices (have CHILDREN) from channels (have PARENT)
        roots: dict[str, Device] = {}
        channels: list[dict] = []

        for entry in raw:
            if "CHILDREN" in entry:
                roots[entry["ADDRESS"]] = Device(
                    address=entry["ADDRESS"],
                    model=entry.get("TYPE", ""),
                )
            elif "PARENT" in entry:
                channels.append(entry)

        for entry in channels:
            parent_addr = entry["PARENT"]
            channel = Channel(
                address=entry["ADDRESS"],
                hm_type=entry.get("TYPE", ""),
                name=entry.get("NAME", entry["ADDRESS"]),
            )
            if parent_addr in roots:
                roots[parent_addr].channels.append(channel)

        return list(roots.values())
