"""Binary sensors: encoder signal (mode-gated), raw + 5s-steady."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZowieboxConfigEntry
from .coordinator import ZowieboxCoordinator
from .entity import ZowieboxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZowieboxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EncoderSignalSensor(coordinator),
            EncoderSignalSteadySensor(coordinator),
        ]
    )


class EncoderSignalSensor(ZowieboxEntity, BinarySensorEntity):
    """On only when the box is in Encoder mode AND an HDMI signal is present.

    The mode gate is the point: a box in Decoder mode may still report an
    HDMI input, but there is no encoder stream to consume then.
    """

    _attr_translation_key = "encoder_signal"

    def __init__(self, coordinator: ZowieboxCoordinator) -> None:
        super().__init__(coordinator, "encoder_signal")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.encoder_signal

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        info = data.input_info
        return {
            "work_mode": "Encoder" if data.is_encoder else "Decoder",
            "hdmi_signal": data.hdmi_signal,
            "resolution": info.get("desc") or None,
            "width": info.get("width"),
            "height": info.get("height"),
            "framerate": info.get("framerate"),
            "audio_sample_rate": info.get("audio_signal"),
        }


class EncoderSignalSteadySensor(ZowieboxEntity, BinarySensorEntity):
    """Encoder signal continuously present for 5 seconds (blip debounce)."""

    _attr_translation_key = "encoder_signal_steady"

    def __init__(self, coordinator: ZowieboxCoordinator) -> None:
        super().__init__(coordinator, "encoder_signal_steady")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.encoder_signal_steady
