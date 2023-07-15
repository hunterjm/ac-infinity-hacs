"""The led ble integration models."""
from __future__ import annotations

from dataclasses import dataclass

from ac_infinity_ble import ACInfinityController

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


@dataclass
class ACInfinityData:
    """Data for the AC Infinity integration."""

    title: str
    device: ACInfinityController
    coordinator: DataUpdateCoordinator
