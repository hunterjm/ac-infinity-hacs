"""Dimmable UIS grow lights."""

import math
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .models import ACInfinityConfigEntry
from .output import ACInfinityOutput, discover_outputs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ACInfinityConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    discover_outputs(
        entry,
        async_add_entities,
        lambda port: (
            [ACInfinityLight(entry, port, "Light")] if port.kind == "light" else []
        ),
    )


class ACInfinityLight(ACInfinityOutput, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def brightness(self) -> int | None:
        port = self.port
        return (
            round(port.level * 255 / 10)
            if port is not None and port.level is not None
            else None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is None:
            await self.set_output(True)
        else:
            await self.set_output(brightness > 0, math.ceil(brightness * 10 / 255))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.set_output(False)
