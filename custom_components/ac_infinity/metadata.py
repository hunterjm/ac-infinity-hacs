"""One controller identity and metadata contract for all entity platforms."""

from ac_infinity_ble import ACInfinityController
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import DOMAIN


def controller_device_info(device: ACInfinityController, title: str) -> DeviceInfo:
    state = device.state
    revisions = state.device_information
    return DeviceInfo(
        connections={(CONNECTION_BLUETOOTH, device.address)},
        identifiers={(DOMAIN, device.address)},
        name=title if title and title != state.name else state.display_name,
        manufacturer="AC Infinity",
        model=state.profile.model_name,
        model_id=state.profile.model_number,
        # The app's Device Information screen labels 2A28 as its current firmware.
        sw_version=revisions.software_revision or revisions.firmware_revision,
        hw_version=revisions.hardware_revision,
    )
