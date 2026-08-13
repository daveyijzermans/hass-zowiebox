"""Selects: work mode, NDI decode source, and the composite source."""

from __future__ import annotations

import asyncio

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZowieboxConfigEntry
from .api import ZowieboxError
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
    """Set the work mode, wait until the device reports it, then enforce the
    matching HDMI loop-out (Encoder→1 = pass local HDMI to the TV, Decoder→0 =
    show the decoded stream).

    The box keeps rejecting config writes (status 00009) for several seconds
    AFTER the new mode already reads back, so the loop-out write retries until
    the device accepts it — a single early attempt is silently lost.
    """
    client = coordinator.client
    # Ask the device, not the (up to poll-interval stale) coordinator snapshot.
    if await client.get_workmode_id() != workmode_id:
        await client.set_workmode(workmode_id)
        for _ in range(20):
            await asyncio.sleep(1)
            try:
                if await client.get_workmode_id() == workmode_id:
                    break
            except ZowieboxError:
                continue  # box may drop requests mid re-init
        else:
            raise HomeAssistantError(
                f"{client.host}: work mode did not reach {workmode_id} within 20s"
            )
    loop_out = 1 if workmode_id == WORKMODE_ENCODER else 0
    last_err: Exception | None = None
    for _ in range(10):
        try:
            output = await client.get_output_info()
            if output.get("loop_out_switch") == loop_out:
                return
            output["loop_out_switch"] = loop_out
            await client.set_output_info(output)
            return
        except ZowieboxError as err:
            last_err = err
            await asyncio.sleep(3)
    raise HomeAssistantError(
        f"{client.host}: device kept rejecting loop-out={loop_out}: {last_err}"
    )


async def _set_decode_source(coordinator: ZowieboxCoordinator, ndi_name: str) -> None:
    """Switch to Decoder mode and subscribe to an NDI source, verified.

    After the mode flip the decode pipeline needs settle time beyond the mode
    read-back — /streamplay calls error until it is ready, and an ndi_recv
    fired into that window is lost. Probe with get_decoder_state until the
    pipeline answers, then subscribe and read the config back to confirm.
    """
    client = coordinator.client
    await _ensure_workmode(coordinator, WORKMODE_DECODER)
    # The box rejects streamplay WRITES ("mpp restart...", status 10000) for a
    # while after the mode flip even once reads answer. Land ONE accepted
    # subscribe (retrying through that window), then verify by polling
    # ndi_get_all for streamplay_status == 1 on the requested source.
    deadline = asyncio.get_event_loop().time() + 90
    last_err: Exception | None = None
    subscribed = False
    while asyncio.get_event_loop().time() < deadline:
        if not subscribed:
            try:
                await client.ndi_recv(ndi_name)
                subscribed = True
            except ZowieboxError as err:
                last_err = err
                await asyncio.sleep(3)
                continue
        await asyncio.sleep(2)
        try:
            for source in await client.ndi_get_all():
                if (
                    source.get("name") == ndi_name
                    and source.get("streamplay_status") == 1
                ):
                    return
        except ZowieboxError as err:
            last_err = err
    raise HomeAssistantError(
        f"{client.host}: NDI stream {ndi_name!r} not playing within 90s: {last_err}"
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
        await _set_decode_source(self.coordinator, option)
        await self.coordinator.async_request_refresh()


class SourceSelect(ZowieboxEntity, SelectEntity):
    """Composite routing select: 'Encoder' = publish own HDMI; any NDI name
    = decode that stream. One entity captures the box's whole routing state,
    so dashboards and automations need a single select per box."""

    _attr_translation_key = "source"

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
            await _set_decode_source(self.coordinator, option)
        await self.coordinator.async_request_refresh()
