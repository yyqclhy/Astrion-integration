"""Astrion 协议单元测试共用的轻量 Home Assistant 测试替身。"""
import asyncio
import copy
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/my_ir"


def load_modules():
    modules = {}
    names = (
        "homeassistant", "homeassistant.components", "homeassistant.components.websocket_api",
        "homeassistant.core", "homeassistant.exceptions", "homeassistant.helpers",
        "homeassistant.helpers.dispatcher", "homeassistant.helpers.event", "voluptuous",
    )
    for name in names:
        modules[name] = types.ModuleType(name)
    package = types.ModuleType("_astrion_gateway_tests")
    package.__path__ = [str(SOURCE)]
    modules[package.__name__] = package
    websocket = modules["homeassistant.components.websocket_api"]
    websocket.websocket_command = lambda schema: lambda function: function
    websocket.async_response = lambda function: function
    modules["homeassistant.core"].callback = lambda function: function
    modules["homeassistant.exceptions"].HomeAssistantError = RuntimeError
    modules["voluptuous"].Required = lambda key: key
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = (
        lambda hass, name: [listener() for listener in tuple(hass.signals.get(name, []))]
    )
    modules["homeassistant.helpers.event"].async_track_time_interval = (
        lambda hass, function, interval: hass.track_timer(function)
    )
    with patch.dict(sys.modules, modules):
        data = importlib.import_module("_astrion_gateway_tests.bluetooth_data")
        gateway = importlib.import_module("_astrion_gateway_tests.gateway")
    return data, gateway


DATA, GATEWAY = load_modules()


class Store:
    def __init__(self):
        self.saved = []
        self.fail = False

    async def async_save(self, data):
        if self.fail:
            raise OSError("disk full")
        self.saved.append(copy.deepcopy(data))


class Bus:
    def __init__(self):
        self.events = []

    def async_fire(self, event_type, data):
        self.events.append((event_type, copy.deepcopy(data)))


class Hass:
    def __init__(self):
        self.data = {
            "astrion": {
                "library": {"devices": {"ir": {"name": "keep"}}, "bluetooth_devices": {}},
                "store": Store(),
            }
        }
        self.signals = {}
        self.timers = []
        self.bus = Bus()

    def track_timer(self, function):
        self.timers.append(function)
        return lambda: self.timers.remove(function)

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)
