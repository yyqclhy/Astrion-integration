"""Astrion 蓝牙集成的独立单元测试。

运行方式（在 Integration 仓库根目录执行）：
    python -m unittest discover -s tests -v

本文件只在开发人员主动运行测试时加载，不参与 Home Assistant 正式运行，
也不会搜索、连接或修改真实蓝牙设备。测试会加载 custom_components/my_ir
中的真实蓝牙业务模块，同时用下方的轻量测试替身模拟 Home Assistant API、
WebSocket 用户、存储、dispatcher 和定时器。

测试通过表示数据校验、库存合并、动态 Entity、网关隔离和失败回滚等已覆盖
规则符合预期；它不能替代真实 HA 加载、APK 上报、蓝牙连接和电视 HID 验收。
"""
import asyncio
import copy
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/my_ir"

def load_modules():
    """用最小 HA API 替身加载真实集成模块，避免测试依赖完整 HA 安装。"""
    modules = {}
    for name in ("homeassistant", "homeassistant.components", "homeassistant.components.websocket_api",
                 "homeassistant.components.remote", "homeassistant.core", "homeassistant.exceptions",
                 "homeassistant.helpers", "homeassistant.helpers.dispatcher", "homeassistant.helpers.event", "voluptuous"):
        modules[name] = types.ModuleType(name)
    package = types.ModuleType("_astrion_bluetooth_tests")
    package.__path__ = [str(SOURCE)]
    modules[package.__name__] = package
    # 装饰器在单元测试中保持透明，保证被测函数仍可直接调用。
    websocket = modules["homeassistant.components.websocket_api"]
    websocket.websocket_command = lambda schema: lambda function: function
    websocket.async_response = lambda function: function
    modules["homeassistant.core"].callback = lambda function: function
    modules["voluptuous"].Required = lambda key: key
    modules["voluptuous"].Optional = lambda key: key
    modules["homeassistant.exceptions"].HomeAssistantError = RuntimeError
    # dispatcher 用同步列表模拟：上传完成后应立即通知对应网关的 Entity。
    dispatcher = modules["homeassistant.helpers.dispatcher"]
    def connect(hass, name, listener):
        hass.signals.setdefault(name, []).append(listener)
        return lambda: hass.signals[name].remove(listener)
    dispatcher.async_dispatcher_connect = connect
    dispatcher.async_dispatcher_send = lambda hass, name: [fn() for fn in tuple(hass.signals.get(name, []))]
    def interval(hass, fn, seconds):
        hass.timers.append(fn)
        return lambda: hass.timers.remove(fn)
    modules["homeassistant.helpers.event"].async_track_time_interval = interval
    # 只实现 BluetoothRemote 在这些测试中实际用到的 RemoteEntity 接口。
    class RemoteEntity:
        async def async_added_to_hass(self): pass
        def async_on_remove(self, callback): self.remove_callback = callback
        def async_write_ha_state(self): self.writes = getattr(self, "writes", 0) + 1
    modules["homeassistant.components.remote"].RemoteEntity = RemoteEntity
    with patch.dict(sys.modules, modules):
        data = importlib.import_module("_astrion_bluetooth_tests.bluetooth_data")
        runtime = importlib.import_module("_astrion_bluetooth_tests.bluetooth")
        remote = importlib.import_module("_astrion_bluetooth_tests.bluetooth_remote")
    return data, runtime, remote

DATA, RUNTIME, REMOTE = load_modules()

def upload(serial="gateway-a", devices=None, **changes):
    """生成一个合法完整快照；各测试只覆盖自己关心的字段。"""
    message = {"id": 1, "type": "astrion/submit_bluetooth_devices", "schema_version": 1,
               "serial_number": serial, "adapter_state": "on", "permission_state": "granted",
               "inventory_complete": True,
               "devices": devices if devices is not None else [{"bluetooth_address": "aa:bb:cc:dd:ee:ff", "name": "TV",
                    "bluetooth_type": "classic", "connection_state": "disconnected", "hid_support": "unknown"}]}
    message.update(changes)
    return message

class Store:
    """记录持久化内容，并可模拟磁盘写入失败。"""
    def __init__(self): self.saved = []; self.fail = False
    async def async_save(self, data):
        if self.fail: raise OSError("disk full")
        self.saved.append(copy.deepcopy(data))

class Hass:
    """最小 hass 对象；保留既有红外数据以验证蓝牙更新不会覆盖它。"""
    def __init__(self):
        self.data = {"astrion": {"library": {"devices": {"ir": {"name": "keep"}}, "bluetooth_devices": {}}, "store": Store()}}
        self.signals = {}; self.timers = []
    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)

class Connection:
    """记录 WebSocket 成功结果或错误码，并模拟管理员身份。"""
    def __init__(self, admin=True): self.user = types.SimpleNamespace(is_admin=admin); self.result = None; self.error = None
    def send_error(self, id, code, text): self.error = code
    def send_result(self, id, result): self.result = result

class BluetoothContractTests(unittest.TestCase):
    """协议与纯数据规则：输入是否合法、标识是否稳定、库存怎样合并。"""

    def test_normalizes_address_and_stable_id(self):
        # MAC 地址统一为大写，稳定 ID 不受输入大小写影响。
        message = DATA.validate_upload(upload())
        self.assertEqual(message["devices"][0]["bluetooth_address"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(DATA.device_id(message["devices"][0]["bluetooth_address"]), "bt_aabbccddeeff")

    def test_invalid_messages_rejected_whole(self):
        # 非法版本、状态、字段类型、长度和设备数量必须整条拒绝。
        invalid = [upload(schema_version=True), upload(schema_version=2), upload(serial_number=""),
                   upload(inventory_complete="true"), upload(adapter_state="off"), upload(permission_state="denied"),
                   upload(devices=[upload()["devices"][0]] * 101)]
        for field, value in (("bluetooth_address", "bad"), ("name", "x" * 129), ("bluetooth_type", []),
                             ("connection_state", "ready"), ("hid_support", True)):
            candidate = upload(); candidate["devices"][0][field] = value; invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError): DATA.validate_upload(candidate)

    def test_case_insensitive_duplicate_rejected(self):
        # 同一 MAC 的大小写变体仍视为重复设备。
        device = upload()["devices"][0]
        with self.assertRaises(ValueError):
            DATA.validate_upload(upload(devices=[device, {**device, "bluetooth_address": "AA:BB:CC:DD:EE:FF"}]))

    def test_off_snapshot_keeps_inventory(self):
        # 蓝牙关闭时只能上报非完整状态，不能借空列表清除库存。
        old = DATA.merge_inventory({}, DATA.validate_upload(upload()))
        message = upload(adapter_state="off", inventory_complete=False); message.pop("devices")
        self.assertEqual(DATA.merge_inventory(old, DATA.validate_upload(message)), old)
        with self.assertRaises(ValueError): DATA.validate_upload(upload(adapter_state="off", inventory_complete=False))

    def test_authoritative_empty_marks_unpaired_and_repair_restores(self):
        # 完整空快照标记未配对；设备再次上报时恢复原记录而非新建重复项。
        old = DATA.merge_inventory({}, DATA.validate_upload(upload()))
        empty = DATA.merge_inventory(old, DATA.validate_upload(upload(devices=[])))
        self.assertFalse(empty["bt_aabbccddeeff"]["paired"])
        repaired = DATA.merge_inventory(empty, DATA.validate_upload(upload()))
        self.assertEqual(repaired, old)
        self.assertNotIn("connection_state", repaired["bt_aabbccddeeff"])

    def test_ble_never_claims_classic_hid_support(self):
        # 纯 BLE 设备不能被集成标记为已支持经典蓝牙 HID。
        message = upload(); message["devices"][0].update(bluetooth_type="le", hid_support="supported")
        self.assertEqual(DATA.validate_upload(message)["devices"][0]["hid_support"], "unsupported")

class BluetoothRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """运行期规则：权限、保存事务、动态 Entity、在线状态与网关生命周期。"""

    async def asyncSetUp(self):
        """每项测试使用新的 HA 数据和 gateway-a 协调器状态。"""
        self.hass = Hass(); self.manager = RUNTIME.coordinator(self.hass); self.manager.start("gateway-a")
        # bluetooth_remote 现在通过正式网关协调器的键查找实例。将该键指向
        # 此旧接口测试替身，使历史迁移测试继续保持隔离。
        self.hass.data["astrion"]["gateway_protocol"] = self.manager

    async def send(self, message=None, admin=True):
        """调用真实 WebSocket 处理函数并返回捕获到的响应。"""
        connection = Connection(admin)
        await RUNTIME.websocket_submit_bluetooth_devices(self.hass, connection, message or upload())
        return connection

    async def test_permission_and_gateway_validation_before_mutation(self):
        # 非管理员和未知网关必须在修改库存前拒绝。
        self.assertEqual((await self.send(admin=False)).error, "permission_denied")
        self.assertEqual((await self.send(upload(serial="other"))).error, "unknown_gateway")
        self.assertEqual(self.manager.inventory("gateway-a"), {})

    async def test_duplicate_uploads_do_not_write_storage(self):
        # 相同快照重复上报不重复写盘，也不得破坏已有红外数据。
        self.assertTrue((await self.send()).result["accepted"])
        await self.send()
        self.assertEqual(len(self.hass.data["astrion"]["store"].saved), 1)
        self.assertIn("ir", self.hass.data["astrion"]["library"]["devices"])

    async def test_entity_listener_failure_does_not_reject_saved_upload(self):
        # Entity/UI 刷新失败不能让 APK 重试一份已经成功持久化的快照。
        def broken_listener():
            raise RuntimeError("entity update failed")
        self.hass.signals[RUNTIME.signal("gateway-a")] = [broken_listener]
        response = await self.send()
        self.assertTrue(response.result["accepted"])
        self.assertTrue(self.manager.inventory("gateway-a"))
        self.assertEqual(len(self.hass.data["astrion"]["store"].saved), 1)

    async def test_storage_error_rolls_back_and_no_runtime_ack(self):
        # 持久化失败时回滚库存和运行态，并返回 storage_error。
        self.hass.data["astrion"]["store"].fail = True
        self.assertEqual((await self.send()).error, "storage_error")
        self.assertEqual(self.manager.inventory("gateway-a"), {})
        self.assertNotIn(
            "gateway-a", self.hass.data["astrion"]["library"]["bluetooth_devices"]
        )
        self.assertEqual(self.manager.live("gateway-a"), {})

    async def test_entities_dynamic_and_gateway_scoped(self):
        # 新设备动态创建一次 Entity，且其他网关上报不能串入本入口。
        added = []; removers = []
        entry = types.SimpleNamespace(data={"app_serial": "gateway-a"}, async_on_unload=removers.append)
        REMOTE.setup_bluetooth_remotes(self.hass, entry, added.extend)
        await self.send(); await self.send()
        self.assertEqual(len(added), 1)
        self.manager.start("gateway-b")
        await self.send(upload(serial="gateway-b"))
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]._attr_unique_id, "gateway-a_bluetooth_aabbccddeeff")
        self.assertEqual(added[0].extra_state_attributes["hid_profile"], DATA.HID_PROFILE)
        removers[0]()
        self.assertEqual(self.hass.signals[RUNTIME.signal("gateway-a")], [])

    async def test_live_state_off_expiry_and_restart(self):
        # 连接状态过期、蓝牙关闭和协调器停止时 Entity 必须不可用。
        connected = upload(); connected["devices"][0].update(connection_state="connected", hid_support="supported")
        await self.send(connected)
        entity = REMOTE.BluetoothRemote(self.manager, "gateway-a", "bt_aabbccddeeff")
        self.assertTrue(entity.is_on)
        self.manager.runtime["gateway-a"]["seen"] -= 181
        self.manager._expire(None)
        self.assertFalse(entity.available)
        self.assertEqual(entity.extra_state_attributes["connection_state"], "disconnected")
        await self.send(connected)
        off = upload(adapter_state="off", inventory_complete=False); off.pop("devices")
        await self.send(off)
        self.assertFalse(entity.available)
        self.assertTrue(entity.extra_state_attributes["paired"])
        self.assertEqual(entity.extra_state_attributes["connection_state"], "disconnected")
        self.manager.stop("gateway-a")
        self.assertFalse(entity.available)
        self.assertEqual(self.hass.timers, [])

    async def test_remote_service_fails_instead_of_sending_ir(self):
        # 蓝牙 Entity 的 HA 服务明确报错，不能误走红外或伪装电源控制。
        await self.send()
        entity = REMOTE.BluetoothRemote(self.manager, "gateway-a", "bt_aabbccddeeff")
        with self.assertRaises(RuntimeError): await entity.async_send_command(["hid_keyboard_up"])
        with self.assertRaises(RuntimeError): await entity.async_turn_on()

    async def test_gateway_removal_is_scoped_and_reload_keeps_inventory(self):
        # 停止/重载保留库存；真正移除网关只删除该网关且支持失败回滚。
        await self.send()
        self.manager.start("gateway-b")
        await self.send(upload(serial="gateway-b"))
        self.manager.stop("gateway-a")
        self.assertTrue(self.manager.inventory("gateway-a"))
        self.hass.data["astrion"]["store"].fail = True
        with self.assertRaises(OSError): await self.manager.remove_gateway("gateway-a")
        self.assertTrue(self.manager.inventory("gateway-a"))
        self.hass.data["astrion"]["store"].fail = False
        await self.manager.remove_gateway("gateway-a")
        self.assertEqual(self.manager.inventory("gateway-a"), {})
        self.assertTrue(self.manager.inventory("gateway-b"))
        self.assertIn("ir", self.hass.data["astrion"]["library"]["devices"])

if __name__ == "__main__":
    # 也支持直接执行该文件；项目级推荐使用文件开头的 discover 命令。
    unittest.main()
