"""Config discovery, JSON persistence and cleanup contracts."""

import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ac_infinity_ble import DeviceInfo
from ac_infinity_ble.const import MANUFACTURER_ID
from bleak.exc import BleakError
from test_lifecycle import integration  # noqa: F401


@pytest.fixture
def config_flow(integration, monkeypatch):  # noqa: F811
    class BaseFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        async_set_unique_id = AsyncMock()
        _abort_if_unique_id_configured = Mock()

        def _async_current_ids(self):
            return set()

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    sys.modules["homeassistant.config_entries"].ConfigFlow = BaseFlow
    bt = sys.modules["homeassistant.components.bluetooth"]
    bt.BluetoothServiceInfoBleak = object
    bt.async_discovered_service_info = Mock(return_value=[])
    module = ModuleType("homeassistant.data_entry_flow")
    module.FlowResult = dict
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return importlib.import_module("custom_components.ac_infinity.config_flow")


def discovery(address="test", data=None):
    if data is None:
        raw = bytearray(27)
        raw[6:13] = b"ABCDE\x03\x0b"
        data = {MANUFACTURER_ID: bytes(raw)}
    return SimpleNamespace(
        address=address,
        manufacturer_data=data,
        device=Mock(),
        advertisement=SimpleNamespace(manufacturer_data=data),
    )


def test_manual_discovery_filters_unrelated_and_malformed_packets(config_flow):
    async def exercise():
        valid = discovery()
        config_flow.async_discovered_service_info.return_value = [
            discovery("other", {}),
            discovery("short", {MANUFACTURER_ID: b"bad"}),
            valid,
        ]
        flow = config_flow.ConfigFlow()
        flow.hass = Mock()
        result = await flow.async_step_user()
        assert result["type"] == "form"
        assert flow._discovered_devices == {"test": valid}

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure", [None, BleakError("disconnected"), asyncio.CancelledError()]
)
def test_config_flow_always_releases_connection_and_stores_json(
    config_flow, monkeypatch, failure
):
    async def exercise():
        controller = SimpleNamespace(
            update=AsyncMock(side_effect=failure),
            stop=AsyncMock(),
            name="G-ABCDE",
            state=DeviceInfo(11, "G-ABCDE", 3, tmp=22),
        )
        monkeypatch.setattr(
            config_flow, "ACInfinityController", Mock(return_value=controller)
        )
        flow = config_flow.ConfigFlow()
        flow.hass = Mock()
        flow._discovered_devices = {"test": discovery()}
        if isinstance(failure, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await flow.async_step_user({"address": "test"})
        else:
            result = await flow.async_step_user({"address": "test"})
            if failure is None:
                assert result["type"] == "create_entry"
                assert result["title"] == "Controller 69 Pro (G-ABCDE)"
                assert json.loads(json.dumps(result["data"])) == {
                    "address": "test",
                    "data": {"type": 11, "name": "G-ABCDE", "version": 3},
                }
            else:
                assert result["errors"] == {"base": "cannot_connect"}
        controller.stop.assert_awaited_once()

    asyncio.run(exercise())
