"""Entity contract tests with a small HA API double; no Bluetooth hardware."""

import asyncio
import importlib
import sys
from dataclasses import replace
from enum import IntFlag
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ac_infinity_ble.device_information import DeviceInformation
from ac_infinity_ble.models import DeviceInfo, PortState
from test_lifecycle import integration  # noqa: F401


@pytest.fixture
def entities(integration, monkeypatch):  # noqa: F811
    class Entity:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.available

    class Feature(IntFlag):
        SET_SPEED = 1
        TURN_ON = 2
        TURN_OFF = 4

    exports = {
        "homeassistant.components.bluetooth.passive_update_coordinator": {
            "PassiveBluetoothCoordinatorEntity": Entity,
        },
        "homeassistant.components.light": {
            "LightEntity": type("LightEntity", (), {}),
            "ATTR_BRIGHTNESS": "brightness",
            "ColorMode": SimpleNamespace(BRIGHTNESS="brightness"),
        },
        "homeassistant.components.fan": {
            "FanEntity": type("FanEntity", (), {}),
            "FanEntityFeature": Feature,
        },
        "homeassistant.components.switch": {
            "SwitchEntity": type("SwitchEntity", (), {})
        },
        "homeassistant.components.number": {
            "NumberEntity": type("NumberEntity", (), {}),
            "NumberMode": SimpleNamespace(SLIDER="slider"),
        },
        "homeassistant.components.sensor": {
            "SensorEntity": type("SensorEntity", (), {}),
            "SensorDeviceClass": SimpleNamespace(
                TEMPERATURE="temperature", HUMIDITY="humidity"
            ),
            "SensorStateClass": SimpleNamespace(MEASUREMENT="measurement"),
        },
        "homeassistant.helpers.entity": {"DeviceInfo": dict},
        "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": object},
        "homeassistant.util": {},
        "homeassistant.util.percentage": {
            "int_states_in_range": lambda limits: 10,
            "ranged_value_to_percentage": lambda limits, value: value * 10,
            "percentage_to_ranged_value": lambda limits, value: value / 10,
        },
    }
    for name, attributes in exports.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    constants = sys.modules["homeassistant.const"]
    constants.PERCENTAGE = "%"
    constants.UnitOfPressure = SimpleNamespace(KPA="kPa")
    constants.UnitOfTemperature = SimpleNamespace(CELSIUS="Â°C")
    sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
        "HomeAssistantError", (Exception,), {}
    )
    return {
        name: importlib.import_module(f"custom_components.ac_infinity.{name}")
        for name in ("output", "fan", "light", "switch", "number", "sensor")
    }


def make_entry(model=11):
    state = DeviceInfo(
        model,
        "Test",
        6,
        ports={
            1: PortState(1, kind="fan", level=3, mode=2),
            2: PortState(2, kind="light", level=4, mode=2),
            3: PortState(3, kind="humidifier", level=5, mode=2),
            4: PortState(4, kind="heater", level=6, mode=2),
            5: PortState(5, kind="air_conditioner", level=7, mode=2),
            6: PortState(6, connected=False, kind="light"),
        },
    )
    device = SimpleNamespace(
        state=state,
        address="00:11:22:33:44:55",
        name="Test",
        set_output=AsyncMock(),
        is_on=False,
        temperature=None,
        humidity=0,
        vpd=None,
    )
    listeners = []
    coordinator = SimpleNamespace(
        available=True, async_add_listener=lambda fn: listeners.append(fn)
    )
    return (
        SimpleNamespace(
            title="Test",
            runtime_data=SimpleNamespace(device=device, coordinator=coordinator),
            async_on_unload=Mock(),
        ),
        listeners,
    )


def test_load_discovery_adds_only_matching_controls_and_handles_hotplug(entities):
    entry, listeners = make_entry()
    added = []

    async def exercise():
        for name in ("fan", "light", "switch", "number"):
            await entities[name].async_setup_entry(None, entry, added.extend)

    asyncio.run(exercise())
    ids = [entity._attr_unique_id for entity in added]
    assert (
        len(ids) == len(set(ids)) == 9
    )  # Aggregate + fan/light + 3 power/level pairs.
    assert not any("port_6" in uid for uid in ids)
    for notify in listeners:
        notify()
    assert len(added) == 9
    entry.runtime_data.device.state = replace(
        entry.runtime_data.device.state,
        ports={
            **entry.runtime_data.device.state.ports,
            7: PortState(7, kind="light", level=1),
        },
    )
    for notify in listeners:
        notify()
    assert len(added) == 10
    light = next(entity for entity in added if "port_2" in entity._attr_unique_id)
    assert light.available
    entry.runtime_data.device.state = replace(
        entry.runtime_data.device.state,
        ports={**entry.runtime_data.device.state.ports, 2: PortState(2, kind="heater")},
    )
    assert not light.available


def test_device_specific_actions_route_to_the_correct_physical_port(entities):
    entry, _ = make_entry()

    async def exercise():
        port = entry.runtime_data.device.state.ports
        light = entities["light"].ACInfinityLight(entry, port[2], "Light")
        assert light.brightness == 102
        await light.async_turn_on(brightness=128)
        entry.runtime_data.device.set_output.assert_awaited_with(2, on=True, level=6)
        await light.async_turn_off()
        entry.runtime_data.device.set_output.assert_awaited_with(
            2, on=False, level=None
        )
        fan = entities["fan"].ACInfinityPortFan(entry, port[1], "Fan")
        assert fan.percentage == 30
        await fan.async_set_percentage(50)
        entry.runtime_data.device.set_output.assert_awaited_with(1, on=True, level=5)
        for number in (3, 4, 5):
            level = entities["number"].ACInfinityLevel(
                entry, port[number], "Output level"
            )
            await level.async_set_native_value(8.0)
            entry.runtime_data.device.set_output.assert_awaited_with(
                number, on=True, level=8
            )
            power = entities["switch"].ACInfinitySwitch(
                entry, port[number], "Manual power"
            )
            await power.async_turn_off()
            entry.runtime_data.device.set_output.assert_awaited_with(
                number, on=False, level=None
            )

    asyncio.run(exercise())


def test_sensor_models_do_not_get_output_entities(entities):
    entry, _ = make_entry(24)
    assert entities["output"].outputs(entry) == []


def test_existing_entity_ids_and_unknown_sensor_values_are_preserved(entities):
    entry, _ = make_entry()
    data = entry.runtime_data
    fan = entities["fan"].ACInfinityFan(data.coordinator, data.device, entry.title)
    assert fan._attr_unique_id == "00:11:22:33:44:55_fan"
    for cls, suffix, value in (
        ("TemperatureSensor", "tmp", None),
        ("HumiditySensor", "hum", 0),
        ("VpdSensor", "vpd", None),
    ):
        entity = getattr(entities["sensor"], cls)(
            data.coordinator, data.device, entry.title
        )
        assert entity.unique_id == "00:11:22:33:44:55_" + suffix
        assert entity._attr_native_value == value


def test_multiple_fans_remain_independent_through_hotplug_and_actions(entities):
    entry, listeners = make_entry()
    entry.runtime_data.device.state = replace(
        entry.runtime_data.device.state,
        ports={
            **entry.runtime_data.device.state.ports,
            2: PortState(2, kind="fan", level=8, mode=2),
        },
    )
    added = []
    asyncio.run(entities["fan"].async_setup_entry(None, entry, added.extend))
    fans = [
        entity
        for entity in added
        if isinstance(entity, entities["fan"].ACInfinityPortFan)
    ]
    assert [fan.percentage for fan in fans] == [30, 80]
    assert [fan._attr_name for fan in fans] == ["Port 1 Fan", "Port 2 Fan"]
    assert len({fan._attr_unique_id for fan in fans}) == 2
    asyncio.run(fans[1].async_set_percentage(50))
    entry.runtime_data.device.set_output.assert_awaited_once_with(2, on=True, level=5)
    entry.runtime_data.device.state = replace(
        entry.runtime_data.device.state,
        ports={
            **entry.runtime_data.device.state.ports,
            1: PortState(1, kind="fan", connected=False),
        },
    )
    assert not fans[0].available and fans[1].available
    entry.runtime_data.device.state = replace(
        entry.runtime_data.device.state,
        ports={
            **entry.runtime_data.device.state.ports,
            1: PortState(1, kind="fan", level=4),
        },
    )
    for notify in listeners:
        notify()
    assert len(added) == 3  # Original aggregate + two ports, no duplicate on reconnect.
    assert fans[0].available and fans[0].percentage == 40


def test_all_platforms_share_common_name_identity_and_real_revisions(entities):
    entry, _ = make_entry()
    data = entry.runtime_data
    data.device.state = replace(
        data.device.state, device_information=DeviceInformation("1.0", "2.0", "3.4.5")
    )
    fan = entities["fan"].ACInfinityFan(data.coordinator, data.device, entry.title)
    light = entities["light"].ACInfinityLight(
        entry, data.device.state.ports[2], "Light"
    )
    sensor = entities["sensor"].TemperatureSensor(
        data.coordinator, data.device, entry.title
    )
    expected = {
        "connections": {("bluetooth", "00:11:22:33:44:55")},
        "identifiers": {("ac_infinity", "00:11:22:33:44:55")},
        "name": "Controller 69 Pro (Test)",
        "manufacturer": "AC Infinity",
        "model": "Controller 69 Pro",
        "model_id": "CTR69P",
        "sw_version": "3.4.5",
        "hw_version": "2.0",
    }
    assert fan.device_info == light.device_info == sensor.device_info == expected
    assert fan.extra_state_attributes["protocol_version"] == 6
    assert light._attr_name == "Port 2 Light"
    data.device.state = replace(
        data.device.state, device_information=DeviceInformation()
    )
    custom = entities["fan"].ACInfinityFan(data.coordinator, data.device, "Grow room")
    assert custom.device_info["name"] == "Grow room"
    assert custom.device_info["sw_version"] is None


def test_legacy_and_port_commands_translate_library_errors(entities):
    entry, _ = make_entry()
    data = entry.runtime_data
    data.device.turn_off = AsyncMock(side_effect=ValueError("bad reply"))
    data.device.set_output.side_effect = ValueError("bad reply")
    fans = [
        entities["fan"].ACInfinityFan(data.coordinator, data.device, entry.title),
        entities["fan"].ACInfinityPortFan(entry, data.device.state.ports[1], "Fan"),
    ]
    for fan in fans:
        with pytest.raises(sys.modules["homeassistant.exceptions"].HomeAssistantError):
            asyncio.run(fan.async_turn_off())
