"""Selects: work mode (Encoder/Decoder) and NDI decode source."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZowieboxConfigEntry
from .const import WORKMODE_DECODER, WORKMODE_ENCODER, WORKMODE_LABELS
from .coordinator import ZowieboxCoordinator
from .entity import ZowieboxEntity
from .ndi import NdiDiscovery, async_get_ndi_discovery


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZowieboxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    discovery = await async_get_ndi_discovery(hass)
    async_add_entities(
        [
            WorkModeSelect(coordinator),
            DecodeSourceSelect(coordinator, discovery),
        ]
    )


class WorkModeSelect(ZowieboxEntity, SelectEntity):
    """Encoder/Decoder work mode, read back from the device every poll —
    a mode changed on the box itself shows up here within one interval."""

    _attr_translation_key = "work_mode"
    _attr_options = [
        WORKMODE_LABELS[WORKMODE_ENCODER],
        WORKMODE_LABELS[WORKMODE_DECODER],
    ]

    def __init__(self, coordinator: ZowieboxCoordinator) -> None:
        super().__init__(coordinator, "work_mode")

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return WORKMODE_LABELS.get(self.coordinator.data.workmode_id)

    async def async_select_option(self, option: str) -> None:
        workmode_id = (
            WORKMODE_ENCODER
            if option == WORKMODE_LABELS[WORKMODE_ENCODER]
            else WORKMODE_DECODER
        )
        await self.coordinator.client.set_workmode(workmode_id)
        # Encoder mode passes the local HDMI through to the TV; Decoder mode
        # must output the decoded stream instead of the loop-through.
        try:
            output = await self.coordinator.client.get_output_info()
            output["loop_out_switch"] = 1 if workmode_id == WORKMODE_ENCODER else 0
            await self.coordinator.client.set_output_info(output)
        except Exception:  # noqa: BLE001 — loopout is best-effort during mode settle
            pass
        await self.coordinator.async_request_refresh()


class DecodeSourceSelect(ZowieboxEntity, SelectEntity):
    """NDI source to decode. Options come from LAN mDNS discovery because the
    box API refuses to enumerate NDI sources while in Encoder mode."""

    _attr_translation_key = "decode_source"

    def __init__(
        self, coordinator: ZowieboxCoordinator, discovery: NdiDiscovery
    ) -> None:
        super().__init__(coordinator, "decode_source")
        self._discovery = discovery

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._discovery.async_add_listener(self._on_sources_changed)
        )

    @callback
    def _on_sources_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        own = self.coordinator.machinename
        options = sorted(
            name
            for name in self._discovery.sources
            # A box cannot decode its own stream; its NDI instance name embeds
            # its machinename, e.g. "MACHINENAME (Channel name)".
            if not (own and own.lower() in name.lower())
        )
        # Keep the active source selectable even if mDNS momentarily drops it.
        current = self.current_option
        if current and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None or not data.is_decoder:
            return None
        return data.ndi_recv_name

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data
        # Selecting a decode source implies Decoder mode (mirrors the box UI).
        if data is not None and not data.is_decoder:
            await self.coordinator.client.set_workmode(WORKMODE_DECODER)
        await self.coordinator.client.ndi_recv(option)
        await self.coordinator.async_request_refresh()
