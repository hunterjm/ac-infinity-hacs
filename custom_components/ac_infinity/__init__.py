"""The ac_infinity integration."""

from __future__ import annotations

import logging

from ac_infinity_ble import ACInfinityController, DeviceInfo
from homeassistant.components import bluetooth
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_SERVICE_DATA,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .coordinator import ACInfinityDataUpdateCoordinator
from .metadata import controller_device_info
from .models import ACInfinityConfigEntry, ACInfinityData

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.NUMBER,
]

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(
    hass: HomeAssistant, entry: ACInfinityConfigEntry
) -> bool:
    """Keep identity and unique IDs while discarding stored live measurements."""
    if entry.version != 1 or entry.minor_version > 3:
        return False
    saved = entry.data.get(CONF_SERVICE_DATA)
    if isinstance(saved, DeviceInfo):
        identity = {"type": saved.type, "name": saved.name, "version": saved.version}
    elif isinstance(saved, dict) and {"type", "name", "version"} <= saved.keys():
        identity = {key: saved[key] for key in ("type", "name", "version")}
    else:
        return False
    try:
        state = DeviceInfo(**identity)
        default_title = state.display_name
    except (TypeError, ValueError):
        return False
    # Titles created by older flows used only the advertised identity. Preserve
    # user titles and all address-based device/entity identifiers.
    title = default_title if entry.title == state.name else entry.title
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_SERVICE_DATA: identity},
        title=title,
        minor_version=3,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ACInfinityConfigEntry) -> bool:
    """Set up ac_infinity from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address.upper(), True)
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find AC Infinity device with address {address}"
        )

    device_info: DeviceInfo | dict = entry.data[CONF_SERVICE_DATA]
    if isinstance(device_info, dict):
        device_info = DeviceInfo(**entry.data[CONF_SERVICE_DATA])
    controller = ACInfinityController(
        ble_device,
        device_info,
        ble_device_provider=lambda: bluetooth.async_ble_device_from_address(
            hass, address.upper(), connectable=True
        ),
    )
    coordinator = ACInfinityDataUpdateCoordinator(hass, _LOGGER, ble_device, controller)

    entry.runtime_data = ACInfinityData(entry.title, controller, coordinator)

    async def async_stop(event: Event) -> None:
        await coordinator.async_shutdown()

    try:
        entry.async_on_unload(coordinator.async_start())
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
        )
        if not await coordinator.async_wait_ready():
            raise ConfigEntryNotReady(f"{address} is not advertising state")

        last_metadata = None

        @callback
        def sync_metadata() -> None:
            nonlocal last_metadata
            metadata = controller_device_info(controller, entry.title)
            if metadata != last_metadata:
                dr.async_get(hass).async_get_or_create(
                    config_entry_id=entry.entry_id, **metadata
                )
                last_metadata = metadata

        sync_metadata()
        entry.async_on_unload(coordinator.async_add_listener(sync_metadata))
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        raise

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ACInfinityConfigEntry
) -> None:
    """Handle options update."""
    data: ACInfinityData = entry.runtime_data
    if entry.title != data.title:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ACInfinityConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: ACInfinityData = entry.runtime_data
        await data.coordinator.async_shutdown()

    return unload_ok
