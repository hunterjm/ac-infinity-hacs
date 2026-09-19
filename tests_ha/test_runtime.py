"""Real HA 2026.9 APIs, with only Bluetooth transport and platform forwarding mocked."""

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ac_infinity_ble import ACInfinityController, DeviceInfo
from bleak.backends.device import BLEDevice
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr

sys.path.insert(0, str(Path(__file__).parents[1]))
from custom_components import ac_infinity
from custom_components.ac_infinity.coordinator import (
    ACInfinityDataUpdateCoordinator,
)

ADDRESS = "00:11:22:33:44:55"


def make_entry():
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain="ac_infinity",
        title="G-Test",
        data={
            "address": ADDRESS,
            "data": {"type": 11, "name": "G-Test", "version": 7, "tmp": 23},
        },
        source="bluetooth",
        unique_id=ADDRESS,
        options={},
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )


@pytest.fixture
def bluetooth_api(monkeypatch):
    # These are the real coordinator's imported API entry points.
    base = importlib.import_module(
        "homeassistant.components.bluetooth.update_coordinator"
    )
    remove = Mock()
    monkeypatch.setattr(base, "async_address_present", Mock(return_value=True))
    monkeypatch.setattr(base, "async_register_callback", Mock(return_value=remove))
    monkeypatch.setattr(base, "async_track_unavailable", Mock(return_value=remove))
    device = BLEDevice(ADDRESS, "Test", {"source": "proxy-a"})
    monkeypatch.setattr(
        ac_infinity.bluetooth,
        "async_ble_device_from_address",
        Mock(return_value=device),
    )
    return device, remove


@pytest.mark.asyncio
async def test_real_entry_migration_setup_metadata_and_unload(
    tmp_path, monkeypatch, bluetooth_api
):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    entry = make_entry()
    hass.config_entries._entries[entry.entry_id] = entry
    monkeypatch.setattr(hass.config_entries, "_async_schedule_save", Mock())
    assert await ac_infinity.async_migrate_entry(hass, entry)
    assert entry.minor_version == 3
    assert entry.unique_id == ADDRESS
    assert entry.data["data"] == {"type": 11, "name": "G-Test", "version": 7}
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        ACInfinityDataUpdateCoordinator,
        "async_wait_ready",
        AsyncMock(return_value=True),
    )
    # Registry lifecycle needs actual HA storage initialization.
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    try:
        assert await ac_infinity.async_setup_entry(hass, entry)
        runtime = entry.runtime_data
        proxy_b = BLEDevice(ADDRESS, "Test", {"source": "proxy-b"})
        ac_infinity.bluetooth.async_ble_device_from_address.return_value = proxy_b
        assert runtime.device._ble_device_provider() is proxy_b
        ac_infinity.bluetooth.async_ble_device_from_address.assert_called_with(
            hass, ADDRESS, connectable=True
        )
        assert isinstance(runtime.coordinator, ACInfinityDataUpdateCoordinator)
        info = dr.async_get(hass).async_get_device_by_identifier(
            ("ac_infinity", ADDRESS), entry.entry_id
        )
        assert info is not None and "Controller 69 Pro" in info.name
        assert await ac_infinity.async_unload_entry(hass, entry)
        assert runtime.device._stopped
        assert runtime.coordinator._shutting_down
        assert not runtime.device._callbacks
        # Entry cleanup may call the unsubscribe returned by async_start again.
        await entry._async_process_on_unload(hass)
        assert bluetooth_api[1].call_count == 2
        assert await ac_infinity.async_migrate_entry(hass, entry)
        assert await ac_infinity.async_setup_entry(hass, entry)
        assert entry.runtime_data.device is not runtime.device
        assert (
            dr.async_get(hass)
            .async_get_device_by_identifier(("ac_infinity", ADDRESS), entry.entry_id)
            .id
            == info.id
        )
        assert await ac_infinity.async_unload_entry(hass, entry)
        await entry._async_process_on_unload(hass)
        assert bluetooth_api[1].call_count == 4
    finally:
        await hass.async_stop()


@pytest.mark.asyncio
async def test_real_coordinator_shutdown_cancels_active_poll(
    tmp_path, monkeypatch, bluetooth_api
):
    hass = HomeAssistant(str(tmp_path))
    hass.set_state(CoreState.running)
    device = ACInfinityController(bluetooth_api[0], DeviceInfo(11, "Test", 7))
    started = asyncio.Event()

    async def update(port=0):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(device, "update", update)
    coordinator = ACInfinityDataUpdateCoordinator(
        hass, logging.getLogger(__name__), bluetooth_api[0], device
    )
    remove = coordinator.async_start()
    try:
        task = asyncio.create_task(
            coordinator._async_update(SimpleNamespace(device=bluetooth_api[0]))
        )
        await started.wait()
        await coordinator.async_shutdown()
        assert task.cancelled()
        assert coordinator._poll_task is None
        assert device._stopped
        assert coordinator._debounced_poll._timer_task is None
        assert not coordinator._needs_poll(
            SimpleNamespace(device=bluetooth_api[0]), None
        )
        remove()
    finally:
        await hass.async_stop()


@pytest.mark.parametrize(
    "platform", ["config_flow", "sensor", "fan", "light", "switch", "number"]
)
def test_all_platforms_import_against_real_ha(platform):
    importlib.import_module(f"custom_components.ac_infinity.{platform}")
