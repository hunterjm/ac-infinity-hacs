"""Constants for the ac_infinity integration."""
from bleak.exc import BleakError

DOMAIN = "ac_infinity"

DEVICE_TIMEOUT = 30
UPDATE_SECONDS = 15

BLEAK_EXCEPTIONS = (AttributeError, BleakError)

DEVICE_MODEL = {1: "Controller 67", 7: "Controller 69", 11: "Controller 69 Pro"}
