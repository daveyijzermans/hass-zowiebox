"""NDI source discovery via Home Assistant's shared zeroconf instance.

The box API cannot enumerate NDI sources unless the box is in Decoder mode
(every /streamplay call returns "workmode is not support!" in Encoder mode),
so the LAN's NDI sources are discovered with mDNS instead: NDI publishers
advertise _ndi._tcp.local. service instances named like
"MACHINENAME (Channel name)". One shared browser serves all config entries.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import HomeAssistant, callback

from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser

from .const import DOMAIN, NDI_SERVICE_TYPE

DATA_NDI = f"{DOMAIN}_ndi_discovery"


class NdiDiscovery:
    """Maintains the live set of NDI source names on the LAN."""

    def __init__(self) -> None:
        self.sources: set[str] = set()
        self._browser: AsyncServiceBrowser | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        # "MACHINENAME (Channel name)._ndi._tcp.local." -> display name
        display = name.removesuffix("." + NDI_SERVICE_TYPE)
        if state_change is ServiceStateChange.Removed:
            changed = display in self.sources
            self.sources.discard(display)
        else:
            changed = display not in self.sources
            self.sources.add(display)
        if changed:
            self._notify()

    async def async_start(self, hass: HomeAssistant) -> None:
        if self._browser is not None:
            return
        aiozc = await ha_zeroconf.async_get_async_instance(hass)
        self._browser = AsyncServiceBrowser(
            aiozc.zeroconf,
            NDI_SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )

    async def async_stop(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None


async def async_get_ndi_discovery(hass: HomeAssistant) -> NdiDiscovery:
    """Get (or start) the hass-wide shared NDI browser."""
    discovery: NdiDiscovery | None = hass.data.get(DATA_NDI)
    if discovery is None:
        discovery = NdiDiscovery()
        hass.data[DATA_NDI] = discovery
        await discovery.async_start(hass)
    return discovery
