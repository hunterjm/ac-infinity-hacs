"""AC Infinity Coordinator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from time import monotonic

from ac_infinity_ble import ACInfinityController
from ac_infinity_ble.const import CallbackType
from ac_infinity_ble.models import DeviceInfo
from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CoreState, HomeAssistant, callback

DEVICE_STARTUP_TIMEOUT = 30
PORT_FRESHNESS = 30
SETTINGS_FRESHNESS = 300
MAX_POLL_BACKOFF = 300


class ACInfinityDataUpdateCoordinator(ActiveBluetoothDataUpdateCoordinator[None]):
    """Class to manage fetching AC Infinity data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        ble_device: BLEDevice,
        controller: ACInfinityController,
    ) -> None:
        """Initialize the Bluetooth coordinator."""
        super().__init__(
            hass=hass,
            logger=logger,
            address=ble_device.address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_update,
            mode=bluetooth.BluetoothScanningMode.ACTIVE,
            connectable=True,
        )
        self.ble_device = ble_device
        self.controller = controller
        self._ready_event = asyncio.Event()
        self._was_unavailable = True
        self._last_telemetry: float | None = None
        self._settings_read: dict[int, tuple[float, str | None, int | None]] = {}
        self._poll_failures = 0
        self._next_poll = 0.0
        self._shutting_down = False
        self._poll_task: asyncio.Task | None = None
        self._remove_controller_callback = controller.register_callback(
            self._controller_updated
        )

    @callback
    def _controller_updated(self, state: DeviceInfo, kind: CallbackType) -> None:
        if kind == CallbackType.NOTIFICATION:
            self._last_telemetry = monotonic()
            for port_id, (_, load_kind, raw_type) in list(self._settings_read.items()):
                if port_id == 0:
                    continue
                port = state.ports.get(port_id)
                if (
                    port is None
                    or not port.connected
                    or (port.kind, port.raw_type) != (load_kind, raw_type)
                ):
                    del self._settings_read[port_id]
        if kind != CallbackType.ADVERTISEMENT:
            self.async_update_listeners()

    def _settings_due(self, now: float) -> list[int]:
        """Settings are independent from running output and advertising cadence."""
        ports = {0} | {port.id for port in self.controller.state.outputs}
        return sorted(
            port
            for port in ports
            if port not in self._settings_read
            or now - self._settings_read[port][0] >= SETTINGS_FRESHNESS
        )

    @callback
    def _needs_poll(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        # Only poll if hass is running, we need to poll,
        # and we actually have a way to connect to the device
        return (
            not self._shutting_down
            and self.controller.state.profile.writable
            and self.hass.state == CoreState.running
            and monotonic() >= self._next_poll
            and (
                self._last_telemetry is None
                or monotonic() - self._last_telemetry >= PORT_FRESHNESS
                or bool(self._settings_due(monotonic()))
            )
            and bool(
                bluetooth.async_ble_device_from_address(
                    self.hass, service_info.device.address, connectable=True
                )
            )
        )

    async def _async_update(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Refresh telemetry and, less often, the saved settings for each load."""
        if self._shutting_down:
            return
        self._poll_task = asyncio.current_task()
        try:
            # An initial GET opens the stream. Re-evaluate discovered ports afterward.
            if 0 in self._settings_due(monotonic()):
                await self._read_settings(0)
            if (
                self._last_telemetry is None
                or monotonic() - self._last_telemetry >= PORT_FRESHNESS
            ):
                await self.controller.refresh_telemetry()
            for port in self._settings_due(monotonic()):
                await self._read_settings(port)
        except Exception:
            self._poll_failures = min(self._poll_failures + 1, 5)
            self._next_poll = monotonic() + min(
                PORT_FRESHNESS * 2 ** (self._poll_failures - 1), MAX_POLL_BACKOFF
            )
            raise
        else:
            self._poll_failures = 0
            self._next_poll = 0.0
        finally:
            self._poll_task = None

    async def _read_settings(self, port_id: int) -> None:
        await self.controller.update(port_id)
        port = self.controller.state.ports.get(port_id)
        if port_id == 0 or (port is not None and port.connected):
            self._settings_read[port_id] = (
                monotonic(),
                port.kind if port else None,
                port.raw_type if port else None,
            )

    async def async_shutdown(self) -> None:
        """Stop polling and release the BLE connection, including on reload."""
        self._shutting_down = True
        try:
            if (
                self._poll_task is not None
                and self._poll_task is not asyncio.current_task()
            ):
                self._poll_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._poll_task
        finally:
            try:
                self._async_stop()
            finally:
                try:
                    if self._remove_controller_callback is not None:
                        self._remove_controller_callback()
                        self._remove_controller_callback = None
                finally:
                    await self.controller.stop()

    @callback
    def _async_handle_unavailable(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Handle the device going unavailable."""
        super()._async_handle_unavailable(service_info)
        self._was_unavailable = True

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Handle a Bluetooth event."""
        self.ble_device = service_info.device
        try:
            self.controller.set_ble_device_and_advertisement_data(
                service_info.device, service_info.advertisement
            )
        except (ValueError, KeyError):
            self.logger.debug("Ignoring malformed AC Infinity advertisement")
            return
        if self.controller.name:
            self._ready_event.set()
        self.logger.debug(
            "%s: AC Infinity data: %s", self.ble_device.address, self.controller.state
        )
        self._was_unavailable = False
        super()._async_handle_bluetooth_event(service_info, change)

    async def async_wait_ready(self) -> bool:
        """Wait for the device to be ready."""
        with contextlib.suppress(asyncio.TimeoutError):
            async with asyncio.timeout(DEVICE_STARTUP_TIMEOUT):
                await self._ready_event.wait()
                return True
        return False
