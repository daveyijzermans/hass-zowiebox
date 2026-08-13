"""Buttons: reboot."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    async_add_entities([RebootButton(entry.runtime_data)])


class RebootButton(ZowieboxEntity, ButtonEntity):
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: ZowieboxCoordinator) -> None:
        super().__init__(coordinator, "reboot")

    async def async_press(self) -> None:
        await self.coordinator.client.reboot()
