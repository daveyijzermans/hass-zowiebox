"""ZowieBox NDI encoder/decoder integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZowieboxClient, ZowieboxError
from .const import (
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import ZowieboxCoordinator
from .ndi import async_get_ndi_discovery

type ZowieboxConfigEntry = ConfigEntry[ZowieboxCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZowieboxConfigEntry) -> bool:
    client = ZowieboxClient(entry.data[CONF_HOST], async_get_clientsession(hass))
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = ZowieboxCoordinator(hass, entry, client, scan_interval)

    # Static device facts (MAC for unique_id, own NDI name for source
    # self-filtering); failure here means the box is unreachable.
    try:
        lan = await client.get_lan_info()
        ndi = await client.get_ndi_info()
    except ZowieboxError as err:
        raise ConfigEntryNotReady(str(err)) from err
    coordinator.mac = lan.get("mac")
    coordinator.machinename = ndi.get("machinename")

    await coordinator.async_config_entry_first_refresh()

    # Shared LAN-wide NDI source browser (survives entry unloads on purpose).
    await async_get_ndi_discovery(hass)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ZowieboxConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZowieboxConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
