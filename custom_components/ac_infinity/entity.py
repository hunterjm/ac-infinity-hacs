"""Common coordinator subscription, metadata and command error handling."""

from collections.abc import Awaitable
from typing import Any

from ac_infinity_ble import ACInfinityController
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import BLEAK_EXCEPTIONS
from .coordinator import ACInfinityDataUpdateCoordinator
from .metadata import controller_device_info


class ACInfinityEntity(
    PassiveBluetoothCoordinatorEntity[ACInfinityDataUpdateCoordinator]
):
    def __init__(
        self,
        coordinator: ACInfinityDataUpdateCoordinator,
        device: ACInfinityController,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_title = name

    @property
    def device_info(self) -> DeviceInfo:
        return controller_device_info(self._device, self._device_title)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._device.state
        revisions = state.device_information
        return {
            "device_type": state.type,
            "protocol_version": state.version,
            "software_revision": revisions.software_revision,
            "firmware_revision": revisions.firmware_revision,
        }

    async def async_command(self, command: Awaitable[None]) -> None:
        try:
            await command
        except (*BLEAK_EXCEPTIONS, ValueError) as ex:
            raise HomeAssistantError(f"AC Infinity command failed: {ex}") from ex

    @callback
    def _async_update_attrs(self) -> None:
        """Platforms with cached attributes override this hook."""

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        self._async_update_attrs()
        self.async_write_ha_state()
