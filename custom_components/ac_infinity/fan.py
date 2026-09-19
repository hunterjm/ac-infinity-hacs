"""The ac_infinity fan platform."""

from __future__ import annotations

import math
from typing import Any

from ac_infinity_ble import ACInfinityController
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .coordinator import ACInfinityDataUpdateCoordinator
from .entity import ACInfinityEntity
from .models import ACInfinityConfigEntry, ACInfinityData
from .output import ACInfinityOutput, discover_outputs

SPEED_RANGE = (1, 10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ACInfinityConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AC Infinity entities."""
    data: ACInfinityData = entry.runtime_data
    discover_outputs(
        entry,
        async_add_entities,
        lambda port: (
            [ACInfinityPortFan(entry, port, "Fan")] if port.kind == "fan" else []
        ),
    )
    if not data.device.state.profile.aggregate_fan:
        return
    async_add_entities([ACInfinityFan(data.coordinator, data.device, entry.title)])


class ACInfinityFan(ACInfinityEntity, FanEntity):
    """Legacy aggregate fan, retaining its original unique ID."""

    _attr_speed_count = int_states_in_range(SPEED_RANGE)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: ACInfinityDataUpdateCoordinator,
        device: ACInfinityController,
        name: str,
    ) -> None:
        """Initialize the aggregate fan."""
        super().__init__(coordinator, device, name)
        self._device = device
        self._attr_name = f"{name} Fan"
        self._attr_unique_id = f"{self._device.address}_fan"
        self._async_update_attrs()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        speed = 0
        if percentage > 0:
            speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))

        await self.async_command(self._device.set_speed(speed))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        speed = None
        if percentage is not None:
            speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self.async_command(self._device.turn_on(speed))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self.async_command(self._device.turn_off())

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        self._attr_is_on = self._device.is_on
        level = self._device.state.fan
        self._attr_percentage = (
            None if level is None else ranged_value_to_percentage(SPEED_RANGE, level)
        )


class ACInfinityPortFan(ACInfinityOutput, FanEntity):
    _attr_speed_count = 10
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    @property
    def percentage(self) -> int | None:
        port = self.port
        return port.level * 10 if port is not None and port.level is not None else None

    async def async_set_percentage(self, percentage: int) -> None:
        await self.set_output(percentage > 0, math.ceil(percentage / 10))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self.set_output(
            True, math.ceil(percentage / 10) if percentage is not None else None
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.set_output(False)
