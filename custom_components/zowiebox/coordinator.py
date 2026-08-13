"""Polling coordinator for a single ZowieBox."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

import logging

from .api import (
    ZowieboxClient,
    ZowieboxConnectionError,
    ZowieboxError,
    ZowieboxWorkmodeError,
)
from .const import DOMAIN, STEADY_SECONDS, WORKMODE_DECODER, WORKMODE_ENCODER

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZowieboxData:
    """State snapshot derived from the device itself (never assumed)."""

    workmode_id: int
    hdmi_signal: bool
    input_info: dict[str, Any] = field(default_factory=dict)
    decoder_state: int | None = None
    ndi_recv_name: str | None = None

    @property
    def is_encoder(self) -> bool:
        return self.workmode_id == WORKMODE_ENCODER

    @property
    def is_decoder(self) -> bool:
        return self.workmode_id == WORKMODE_DECODER

    @property
    def encoder_signal(self) -> bool:
        """The gate this integration exists for: an HDMI signal only counts
        as an encoder stream when the box is actually in Encoder mode."""
        return self.is_encoder and self.hdmi_signal


class ZowieboxCoordinator(DataUpdateCoordinator[ZowieboxData]):
    """Poll work mode + HDMI input (+ decode state when in Decoder mode)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ZowieboxClient,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{client.host}",
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.machinename: str | None = None
        self.mac: str | None = None
        self._signal_on_since: float | None = None

    async def _async_update_data(self) -> ZowieboxData:
        try:
            workmode_id = await self.client.get_workmode_id()
            input_info = await self.client.get_input_info()
        except ZowieboxConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except ZowieboxError as err:
            raise UpdateFailed(str(err)) from err

        data = ZowieboxData(
            workmode_id=workmode_id,
            hdmi_signal=input_info.get("hdmi_signal") == 1,
            input_info=input_info,
        )

        if data.is_decoder:
            # These calls are rejected outright in Encoder mode (status
            # 00004), so only ask when the device says it is a decoder.
            # The active subscription is the ndi_get_all entry with
            # streamplay_status == 1 (ndi_get_recv_config never carries it).
            try:
                data.decoder_state = await self.client.get_decoder_state()
                for source in await self.client.ndi_get_all():
                    if source.get("streamplay_status") == 1:
                        data.ndi_recv_name = source.get("name")
                        break
            except ZowieboxWorkmodeError:
                pass  # mode flipped between calls; next poll settles it
            except ZowieboxError as err:
                _LOGGER.debug("decode-state read failed: %s", err)

        # Track how long the encoder signal has been continuously present.
        if data.encoder_signal:
            if self._signal_on_since is None:
                self._signal_on_since = time.monotonic()
        else:
            self._signal_on_since = None

        return data

    @property
    def encoder_signal_steady(self) -> bool:
        """Encoder signal present continuously for STEADY_SECONDS."""
        return (
            self._signal_on_since is not None
            and time.monotonic() - self._signal_on_since >= STEADY_SECONDS
        )
