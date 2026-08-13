"""Base entity for ZowieBox."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZowieboxCoordinator


class ZowieboxEntity(CoordinatorEntity[ZowieboxCoordinator]):
    """Common device info / unique id plumbing."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZowieboxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        unique_base = coordinator.mac or coordinator.client.host
        self._attr_unique_id = f"{unique_base}_{key}"
        connections = (
            {(CONNECTION_NETWORK_MAC, coordinator.mac)} if coordinator.mac else set()
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_base)},
            connections=connections,
            name=coordinator.config_entry.title,
            manufacturer="ZowieTek",
            model="ZowieBox",
            configuration_url=f"http://{coordinator.client.host}/",
        )
