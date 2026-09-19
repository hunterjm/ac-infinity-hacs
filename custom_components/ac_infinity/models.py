"""Runtime data for AC Infinity."""

from __future__ import annotations

from dataclasses import dataclass

from ac_infinity_ble import ACInfinityController
from homeassistant.config_entries import ConfigEntry

from .coordinator import ACInfinityDataUpdateCoordinator


@dataclass
class ACInfinityData:
    """Data for the AC Infinity integration."""

    title: str
    device: ACInfinityController
    coordinator: ACInfinityDataUpdateCoordinator


ACInfinityConfigEntry = ConfigEntry[ACInfinityData]
