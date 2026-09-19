"""Shared discovery and state for device-specific AC Infinity output controls."""

from collections.abc import Callable
from typing import Any

from ac_infinity_ble.models import PortState
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ACInfinityEntity
from .models import ACInfinityConfigEntry


def outputs(entry: ACInfinityConfigEntry) -> list[PortState]:
    return list(entry.runtime_data.device.state.outputs)


@callback
def discover_outputs(
    entry: ACInfinityConfigEntry,
    add: AddEntitiesCallback,
    factory: Callable[[PortState], list[Any]],
) -> None:
    seen: set[tuple[int, str | None]] = set()

    @callback
    def update() -> None:
        for port in outputs(entry):
            key = (port.id, port.kind)
            if key not in seen:
                seen.add(key)
                add(factory(port))

    entry.async_on_unload(entry.runtime_data.coordinator.async_add_listener(update))
    update()


class ACInfinityOutput(ACInfinityEntity):
    _attr_has_entity_name = True

    def __init__(
        self, entry: ACInfinityConfigEntry, port: PortState, suffix: str
    ) -> None:
        super().__init__(
            entry.runtime_data.coordinator, entry.runtime_data.device, entry.title
        )
        self._device = entry.runtime_data.device
        self._port_id, self._kind = port.id, port.kind
        self._entry = entry
        label = (port.kind or "Output").replace("_", " ").title()
        self._attr_name = f"Port {port.id} {label}" if port.id else label
        if suffix != label:
            self._attr_name += f" {suffix}"
        suffix_id = suffix.lower().replace(" ", "_")
        self._attr_unique_id = (
            f"{self._device.address}_port_{port.id}_{port.kind}_{suffix_id}"
        )

    @property
    def port(self) -> PortState | None:
        return next(
            (
                p
                for p in outputs(self._entry)
                if p.id == self._port_id and p.kind == self._kind
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.port is not None

    @property
    def is_on(self) -> bool | None:
        port = self.port
        if self._device.state.profile.separate_power:
            return port.power if port is not None else None
        if port is None or port.mode is None:
            return None
        return port.mode != 1

    async def set_output(self, on: bool, level: int | None = None) -> None:
        await self.async_command(
            self._device.set_output(self._port_id, on=on, level=level)
        )
