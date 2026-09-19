"""Native 0-10 output levels for humidifiers, heaters, and air conditioners."""

from homeassistant.components.number import NumberEntity, NumberMode
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
            [ACInfinityLevel(entry, port, "Output level")]
            if port.kind in ("humidifier", "dehumidifier", "heater", "air_conditioner")
            else []
        ),
    )


class ACInfinityLevel(ACInfinityOutput, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> int | None:
        return self.port.level if self.port is not None else None

    async def async_set_native_value(self, value: float) -> None:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("Output level must be a whole number")
        await self.set_output(value > 0, int(value))
