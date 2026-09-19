"""Constants for the ac_infinity integration."""

from ac_infinity_ble.exceptions import CharacteristicMissingError
from bleak.exc import BleakError

DOMAIN = "ac_infinity"

DEVICE_TIMEOUT = 30
UPDATE_SECONDS = 15

BLEAK_EXCEPTIONS = (BleakError, TimeoutError, CharacteristicMissingError)
