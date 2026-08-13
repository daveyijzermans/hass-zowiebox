"""Sensors: HDMI input resolution."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    async_add_entities([InputResolutionSensor(entry.runtime_data)])


class InputResolutionSensor(ZowieboxEntity, SensorEntity):
    """Current HDMI input format, e.g. '1080p59.94'; empty when no signal."""

    _attr_translation_key = "input_resolution"

    def __init__(self, coordinator: ZowieboxCoordinator) -> None:
        super().__init__(coordinator, "input_resolution")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or not data.hdmi_signal:
            return None
        return data.input_info.get("desc") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        info = data.input_info
        return {
            "width": info.get("width"),
            "height": info.get("height"),
            "framerate": info.get("framerate"),
            "audio_sample_rate": info.get("audio_signal"),
        }
