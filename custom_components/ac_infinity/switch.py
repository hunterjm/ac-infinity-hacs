"""Manual power controls for outlets and environmental appliances."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
            [ACInfinitySwitch(entry, port, "Manual power")]
            if port.kind not in ("light", "fan")
            else []
        ),
    )


class ACInfinitySwitch(ACInfinityOutput, SwitchEntity):
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.set_output(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.set_output(False)
