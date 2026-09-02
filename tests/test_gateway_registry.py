"""蓝牙实体注册表与设备注册表的协调测试。"""
import sys
import types
import unittest
from unittest.mock import patch

from support import GATEWAY, Hass


class RegistryEntry:
    """清理逻辑单元测试所需的最小实体注册表记录。"""

    def __init__(self, entity_id, unique_id, device_id, platform="astrion"):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.device_id = device_id
        self.platform = platform
        self.domain = entity_id.split(".", 1)[0]


class EntityRegistry:
    """在内存中模拟 gateway.py 使用的注册表接口。"""

    def __init__(self, entries):
        self.entities = {entry.entity_id: entry for entry in entries}

    def async_remove(self, entity_id):
        self.entities.pop(entity_id, None)


class DeviceEntry:
    def __init__(self, device_id, identifiers):
        self.id = device_id
        self.identifiers = identifiers


class DeviceRegistry:
    """用于验证记录确实被移除的内存设备注册表。"""

    def __init__(self, devices):
        self.devices = {device.id: device for device in devices}

    def async_get_device(self, identifiers):
        return next(
            (device for device in self.devices.values() if device.identifiers & identifiers),
            None,
        )

    def async_remove_device(self, device_id):
        self.devices.pop(device_id, None)


class BluetoothRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_removes_only_stale_bluetooth_child(self):
        hass = Hass()
        entries = EntityRegistry([
            RegistryEntry("remote.current", "gateway-a_bluetooth_aabb", "current"),
            RegistryEntry("button.current", "gateway-a_bluetooth_aabb_unpair", "current"),
            RegistryEntry("remote.stale", "gateway-a_bluetooth_ccdd", "stale"),
            RegistryEntry("button.stale", "gateway-a_bluetooth_ccdd_unpair", "stale"),
            RegistryEntry("button.refresh", "gateway-a_refresh", "gateway"),
            RegistryEntry("remote.other", "gateway-b_bluetooth_ccdd", "other"),
        ])
        devices = DeviceRegistry([
            DeviceEntry("current", {("astrion", "gateway-a_bluetooth_aabb")}),
            DeviceEntry("stale", {("astrion", "gateway-a_bluetooth_ccdd")}),
            DeviceEntry("gateway", {("astrion", "gateway-a")}),
            DeviceEntry("other", {("astrion", "gateway-b_bluetooth_ccdd")}),
        ])

        entity_module = types.ModuleType("homeassistant.helpers.entity_registry")
        entity_module.async_get = lambda _hass: entries
        entity_module.async_entries_for_device = lambda registry, device_id, **_kwargs: [
            entry for entry in registry.entities.values() if entry.device_id == device_id
        ]
        device_module = types.ModuleType("homeassistant.helpers.device_registry")
        device_module.async_get = lambda _hass: devices
        homeassistant_module = types.ModuleType("homeassistant")
        helpers_module = types.ModuleType("homeassistant.helpers")
        helpers_module.entity_registry = entity_module
        helpers_module.device_registry = device_module

        # gateway.py 延迟导入注册表，因此这些独立协议测试
        # 无需依赖真实 HA 环境中的模块。
        with patch.dict(sys.modules, {
            "homeassistant": homeassistant_module,
            "homeassistant.helpers": helpers_module,
            "homeassistant.helpers.entity_registry": entity_module,
            "homeassistant.helpers.device_registry": device_module,
        }):
            await GATEWAY.async_reconcile_bluetooth_registry(
                hass, "gateway-a", {"bt_aabb": {"paired": True}}
            )

        self.assertEqual(
            set(entries.entities),
            {"remote.current", "button.current", "button.refresh", "remote.other"},
        )
        self.assertEqual(set(devices.devices), {"current", "gateway", "other"})


if __name__ == "__main__":
    unittest.main()
