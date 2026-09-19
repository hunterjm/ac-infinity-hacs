"""Verify advertisement-driven scheduling independently of the wall clock."""

import asyncio
import importlib
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from ac_infinity_ble import CallbackType, DeviceInfo, PortState
from test_lifecycle import integration as integration


def setup_polling(integration, monkeypatch):
    module = importlib.import_module("custom_components.ac_infinity.coordinator")
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr(module, "monotonic", clock)
    controller = Mock(
        update=AsyncMock(), refresh_telemetry=AsyncMock(), stop=AsyncMock()
    )
    controller.state = DeviceInfo(11, "Test", 7, ports={1: PortState(1, kind="fan")})
    service = SimpleNamespace(device=SimpleNamespace(address="test"))
    coordinator = module.ACInfinityDataUpdateCoordinator(
        SimpleNamespace(state="running"),
        logging.getLogger(__name__),
        service.device,
        controller,
    )
    coordinator.async_update_listeners = Mock()

    async def telemetry():
        coordinator._controller_updated(controller.state, CallbackType.NOTIFICATION)

    controller.refresh_telemetry.side_effect = telemetry
    return coordinator, controller, clock, service


def test_polling_separates_actual_output_from_saved_settings(integration, monkeypatch):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        assert c._needs_poll(service, None)
        await c._async_update(service)
        assert device.update.await_args_list == [call(0), call(1)]
        assert not c._needs_poll(service, 0)
        clock.return_value += 30
        assert c._needs_poll(service, 30)
        await c._async_update(service)
        assert device.update.await_count == 2
        assert device.refresh_telemetry.await_count == 2
        clock.return_value = 1300
        await c._async_update(service)
        assert device.update.await_args_list == [call(0), call(1), call(0), call(1)]

    asyncio.run(exercise())


def test_notifications_defer_port_poll_but_advertisements_do_not(
    integration, monkeypatch
):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        await c._async_update(service)
        clock.return_value += 30
        c._controller_updated(device.state, CallbackType.ADVERTISEMENT)
        assert c._needs_poll(service, 30)
        c._controller_updated(device.state, CallbackType.NOTIFICATION)
        assert not c._needs_poll(service, 30)

    asyncio.run(exercise())


def test_new_or_changed_load_reads_settings_without_waiting_five_minutes(
    integration, monkeypatch
):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        await c._async_update(service)
        device.state = replace(device.state, ports={1: PortState(1, kind="light")})
        c._controller_updated(device.state, CallbackType.NOTIFICATION)
        assert c._needs_poll(service, 0)
        await c._async_update(service)
        assert device.update.await_args_list == [call(0), call(1), call(1)]
        device.state = replace(device.state, ports={1: PortState(1, connected=False)})
        c._controller_updated(device.state, CallbackType.NOTIFICATION)
        assert not c._settings_due(clock())

    asyncio.run(exercise())


def test_poll_failures_back_off_and_recover(integration, monkeypatch):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        device.update.side_effect = RuntimeError("offline")
        for delay in (30, 60, 120, 240, 300, 300):
            with pytest.raises(RuntimeError):
                await c._async_update(service)
            assert not c._needs_poll(service, None)
            clock.return_value += delay
            assert c._needs_poll(service, None)
        device.update.side_effect = None
        await c._async_update(service)
        assert c._poll_failures == 0
        assert c._next_poll == 0

    asyncio.run(exercise())


def test_poll_cancellation_does_not_become_failure_backoff(integration, monkeypatch):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        device.update.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await c._async_update(service)
        assert c._poll_failures == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("reason", ["sensor", "starting", "no-route"])
def test_polling_requires_writable_running_connectable_device(
    integration, monkeypatch, reason
):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        if reason == "sensor":
            device.state = DeviceInfo(14, "Test", 4)
        elif reason == "starting":
            c.hass.state = "starting"
        else:
            integration.bluetooth.async_ble_device_from_address.return_value = None
        assert not c._needs_poll(service, None)

    asyncio.run(exercise())


def test_poll_cleanup_failure_cannot_skip_shutdown(integration, monkeypatch):
    async def exercise():
        c, device, clock, service = setup_polling(integration, monkeypatch)
        started = asyncio.Event()

        async def update(port):
            started.set()
            try:
                await asyncio.Future()
            finally:
                raise RuntimeError("cleanup failed")

        device.update.side_effect = update
        task = asyncio.create_task(c._async_update(service))
        await started.wait()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await c.async_shutdown()
        assert task.done()
        c._async_stop.assert_called_once()
        device.stop.assert_awaited_once()

    asyncio.run(exercise())
