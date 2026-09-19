"""Exercise integration entry points with a minimal mocked Home Assistant API."""

import asyncio
import importlib
import logging
import sys
from dataclasses import replace
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ac_infinity_ble import DeviceInfo


@pytest.fixture
def integration(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    module_names = [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.bluetooth",
        "homeassistant.components.bluetooth.active_update_coordinator",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
    ]
    modules = {name: ModuleType(name) for name in module_names}

    class BaseCoordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, **kwargs):
            self.hass = hass
            self.logger = logger
            self._async_stop = Mock()
            self.listeners = []

        def async_add_listener(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

        def async_start(self):
            return self._async_stop

    class Platform(Enum):
        SENSOR = "sensor"
        FAN = "fan"
        LIGHT = "light"
        SWITCH = "switch"
        NUMBER = "number"

    modules[
        "homeassistant.components.bluetooth"
    ].BluetoothScanningMode = SimpleNamespace(ACTIVE="active")
    modules["homeassistant.components.bluetooth"].async_ble_device_from_address = Mock(
        return_value=SimpleNamespace(address="00:11:22:33:44:55")
    )
    modules[
        "homeassistant.components.bluetooth.active_update_coordinator"
    ].ActiveBluetoothDataUpdateCoordinator = BaseCoordinator
    modules["homeassistant.config_entries"].ConfigEntry = BaseCoordinator
    constants = modules["homeassistant.const"]
    constants.CONF_ADDRESS = "address"
    constants.CONF_SERVICE_DATA = "data"
    constants.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    constants.Platform = Platform
    core = modules["homeassistant.core"]
    core.Event = object
    core.HomeAssistant = object
    core.CoreState = SimpleNamespace(running="running")
    core.callback = lambda fn: fn
    modules["homeassistant.exceptions"].ConfigEntryNotReady = type(
        "ConfigEntryNotReady", (Exception,), {}
    )
    registry = modules["homeassistant.helpers.device_registry"]
    registry.CONNECTION_BLUETOOTH = "bluetooth"
    registry.DeviceInfo = dict
    registry.async_get = Mock(return_value=Mock())
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components."):
            monkeypatch.delitem(sys.modules, name)
    component = importlib.import_module("custom_components.ac_infinity")
    yield component
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components."):
            del sys.modules[name]


def setup_objects(integration, monkeypatch):
    controller = Mock(stop=AsyncMock())
    controller.state = DeviceInfo(11, "G-ABCDE", 3)
    controller.address = "00:11:22:33:44:55"
    monkeypatch.setattr(
        integration, "ACInfinityController", Mock(return_value=controller)
    )
    monkeypatch.setattr(
        integration.ACInfinityDataUpdateCoordinator,
        "async_wait_ready",
        AsyncMock(return_value=True),
    )
    hass = SimpleNamespace(
        data={},
        bus=Mock(),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        ),
    )
    entry = SimpleNamespace(
        entry_id="test-entry",
        title="Controller 69 Pro",
        data={
            "address": "00:11:22:33:44:55",
            "data": DeviceInfo(type=9, name="Test", version=3),
        },
        async_on_unload=Mock(),
        add_update_listener=Mock(),
    )
    return controller, hass, entry


def test_successful_unload_stops_polling_and_releases_ble(integration, monkeypatch):
    async def exercise():
        controller, hass, entry = setup_objects(integration, monkeypatch)
        await integration.async_setup_entry(hass, entry)
        coordinator = entry.runtime_data.coordinator
        assert await integration.async_unload_entry(hass, entry)
        coordinator._async_stop.assert_called_once()
        controller.stop.assert_awaited_once()

    asyncio.run(exercise())


def test_failed_platform_unload_keeps_connection(integration, monkeypatch):
    async def exercise():
        controller, hass, entry = setup_objects(integration, monkeypatch)
        await integration.async_setup_entry(hass, entry)
        hass.config_entries.async_unload_platforms.return_value = False
        assert not await integration.async_unload_entry(hass, entry)
        controller.stop.assert_not_awaited()
        assert entry.runtime_data is not None

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["not-ready", "platform", "cancel", "start"])
def test_setup_failure_releases_ble(integration, monkeypatch, failure):
    async def exercise():
        controller, hass, entry = setup_objects(integration, monkeypatch)
        expected_error = RuntimeError
        if failure == "start":
            monkeypatch.setattr(
                integration.ACInfinityDataUpdateCoordinator,
                "async_start",
                Mock(side_effect=RuntimeError("start failed")),
            )
        elif failure == "not-ready":
            wait_ready = integration.ACInfinityDataUpdateCoordinator.async_wait_ready
            wait_ready.return_value = False
            expected_error = integration.ConfigEntryNotReady
        else:
            if failure == "cancel":
                expected_error = asyncio.CancelledError
            hass.config_entries.async_forward_entry_setups.side_effect = expected_error
        with pytest.raises(expected_error):
            await integration.async_setup_entry(hass, entry)
        controller.stop.assert_awaited_once()

    asyncio.run(exercise())


def test_home_assistant_stop_event_releases_ble(integration, monkeypatch):
    async def exercise():
        controller, hass, entry = setup_objects(integration, monkeypatch)
        await integration.async_setup_entry(hass, entry)
        event_name, stop_callback = hass.bus.async_listen_once.call_args.args
        assert event_name == "homeassistant_stop"
        await stop_callback(object())
        controller.stop.assert_awaited_once()
        entry.async_on_unload.assert_any_call(hass.bus.async_listen_once.return_value)

    asyncio.run(exercise())


def test_callback_cleanup_failure_does_not_skip_disconnect(integration):
    async def exercise():
        controller = Mock(stop=AsyncMock())
        coordinator = integration.ACInfinityDataUpdateCoordinator(
            object(),
            logging.getLogger(__name__),
            SimpleNamespace(address="test"),
            controller,
        )
        coordinator._async_stop.side_effect = RuntimeError("callback cleanup failed")
        with pytest.raises(RuntimeError):
            await coordinator.async_shutdown()
        controller.stop.assert_awaited_once()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "saved",
    [
        DeviceInfo(11, "Test", 3, tmp=21),
        {"type": 11, "name": "Test", "version": 3, "tmp": 21},
    ],
)
def test_migration_keeps_identity_and_drops_live_measurements(integration, saved):
    async def exercise():
        entry = SimpleNamespace(
            version=1,
            minor_version=2,
            title="Test",
            data={"address": "AA:BB", "data": saved},
        )
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock())
        )
        assert await integration.async_migrate_entry(hass, entry)
        update = hass.config_entries.async_update_entry.call_args.kwargs
        assert update["data"] == {
            "address": "AA:BB",
            "data": {"type": 11, "name": "Test", "version": 3},
        }
        assert update["minor_version"] == 3
        assert update["title"] == "Controller 69 Pro (Test)"

    asyncio.run(exercise())


@pytest.mark.parametrize("minor", [1, 2, 3])
@pytest.mark.parametrize("title", ["G-ABCDE", "Grow room"])
def test_migration_preserves_custom_titles_and_is_idempotent(integration, minor, title):
    async def exercise():
        entry = SimpleNamespace(
            version=1,
            minor_version=minor,
            title=title,
            unique_id="AA:BB",
            data={
                "address": "AA:BB",
                "data": {
                    "type": 11,
                    "name": "G-ABCDE",
                    "version": 6,
                },
                "other_option": True,
            },
        )

        def apply(entry, **kwargs):
            entry.__dict__.update(kwargs)

        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=apply))
        )
        assert await integration.async_migrate_entry(hass, entry)
        once = dict(entry.__dict__)
        assert await integration.async_migrate_entry(hass, entry)
        assert entry.__dict__ == once
        assert entry.title == (
            "Controller 69 Pro (G-ABCDE)" if title == "G-ABCDE" else title
        )
        assert entry.unique_id == entry.data["address"] == "AA:BB"
        assert entry.data["other_option"] is True
        assert entry.minor_version == 3

    asyncio.run(exercise())


@pytest.mark.parametrize("version,minor", [(2, 1), (1, 4)])
def test_migration_rejects_newer_config_versions(integration, version, minor):
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    assert not asyncio.run(
        integration.async_migrate_entry(
            hass, SimpleNamespace(version=version, minor_version=minor)
        )
    )
    hass.config_entries.async_update_entry.assert_not_called()


def test_registry_metadata_refreshes_after_optional_ble_reads(integration, monkeypatch):
    from ac_infinity_ble.device_information import DeviceInformation

    async def exercise():
        controller, hass, entry = setup_objects(integration, monkeypatch)
        await integration.async_setup_entry(hass, entry)
        registry = integration.dr.async_get(hass)
        assert registry.async_get_or_create.call_args.kwargs["sw_version"] is None
        controller.state = replace(
            controller.state,
            device_information=DeviceInformation("1.0", "2.0", "3.4.5"),
        )
        for notify in entry.runtime_data.coordinator.listeners:
            notify()
        metadata = registry.async_get_or_create.call_args.kwargs
        assert metadata["sw_version"] == "3.4.5"
        assert metadata["hw_version"] == "2.0"
        calls = registry.async_get_or_create.call_count
        for notify in entry.runtime_data.coordinator.listeners:
            notify()
        assert registry.async_get_or_create.call_count == calls

    asyncio.run(exercise())
