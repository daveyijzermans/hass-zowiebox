"""Selects: work mode, NDI decode source, and the composite source."""

from __future__ import annotations

import asyncio

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
            SourceSelect(coordinator, discovery),
        ]
    )


async def _ensure_workmode(coordinator: ZowieboxCoordinator, workmode_id: int) -> None:
    """Set the work mode and wait until the device reports it (the box takes
    a few seconds to re-init its pipeline; its own web UI polls the same way)."""
    if (
        coordinator.data is not None
        and coordinator.data.workmode_id == workmode_id
    ):
        return
    client = coordinator.client
    await client.set_workmode(workmode_id)
    for _ in range(15):
        await asyncio.sleep(1)
        if await client.get_workmode_id() == workmode_id:
            break
    # Encoder mode passes the local HDMI through to the TV; Decoder mode must
    # output the decoded stream instead of the loop-through.
    try:
        output = await client.get_output_info()
        output["loop_out_switch"] = 1 if workmode_id == WORKMODE_ENCODER else 0
        await client.set_output_info(output)
    except Exception:  # noqa: BLE001 — loopout is best-effort during mode settle
        pass


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
        await _ensure_workmode(self.coordinator, workmode_id)
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
        # Selecting a decode source implies Decoder mode (mirrors the box UI).
        await _ensure_workmode(self.coordinator, WORKMODE_DECODER)
        await self.coordinator.client.ndi_recv(option)
        await self.coordinator.async_request_refresh()


class SourceSelect(ZowieboxEntity, SelectEntity):
    """Composite routing select: 'Encoder' = publish own HDMI; any NDI name
    = decode that stream. One entity captures the box's whole routing state,
    so dashboards and automations need a single select per box."""

    _attr_translation_key = "stream_source"

    def __init__(
        self, coordinator: ZowieboxCoordinator, discovery: NdiDiscovery
    ) -> None:
        super().__init__(coordinator, "source")
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
            if not (own and own.lower() in name.lower())
        )
        current = self.current_option
        if current and current not in options and current != WORKMODE_LABELS[WORKMODE_ENCODER]:
            options.append(current)
        return [WORKMODE_LABELS[WORKMODE_ENCODER], *options]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        if data.is_encoder:
            return WORKMODE_LABELS[WORKMODE_ENCODER]
        return data.ndi_recv_name

    async def async_select_option(self, option: str) -> None:
        if option == WORKMODE_LABELS[WORKMODE_ENCODER]:
            await _ensure_workmode(self.coordinator, WORKMODE_ENCODER)
        else:
            await _ensure_workmode(self.coordinator, WORKMODE_DECODER)
            await self.coordinator.client.ndi_recv(option)
        await self.coordinator.async_request_refresh()
