"""使用轻量 HA 测试替身验证网关协议 v1 状态机。"""
import copy
import asyncio
import unittest
import uuid

from support import DATA, GATEWAY, LEARNING, Hass


def envelope(route, boot_id, sequence, payload, serial="gateway-a", request_id=1):
    return {
        "id": request_id,
        "type": route,
        "protocol_version": 1,
        "schema_version": 1,
        "gateway_serial": serial,
        "boot_id": boot_id,
        "sequence": sequence,
        "payload": payload,
    }


def heartbeat(boot_id, sequence=0, serial="gateway-a"):
    return envelope("astrion/gateway/heartbeat", boot_id, sequence, {
        "app_version": "1.5.0",
        "app_build": 73,
        "platform": "android",
        "platform_version": "12",
        "capabilities": [
            "bluetooth_hid", "bluetooth_inventory", "bluetooth_unpair",
            "device_refresh", "navigation_control",
        ],
    }, serial)


def inventory(boot_id, sequence=0, devices=None, serial="gateway-a"):
    if devices is None:
        devices = [{
            "bluetooth_address": "AA:BB:CC:DD:EE:FF",
            "name": "TV",
            "bluetooth_type": "classic",
            "connection_state": "connected",
            "hid_support": "supported",
        }]
    return envelope("astrion/bluetooth/inventory", boot_id, sequence, {
        "adapter_state": "on",
        "permission_state": "granted",
        "inventory_complete": True,
        "devices": devices,
    }, serial)


class GatewayProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = Hass()
        self.manager = GATEWAY.coordinator(self.hass)
        self.manager.start("gateway-a")
        self.boot = str(uuid.uuid4())

    async def online_with_inventory(self):
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot)))
        return await self.manager.upload_inventory(DATA.validate_inventory(inventory(self.boot)))

    async def test_inventory_does_not_create_online_lease(self):
        with self.assertRaisesRegex(ValueError, "gateway_not_ready"):
            await self.manager.upload_inventory(DATA.validate_inventory(inventory(self.boot)))
        self.assertFalse(self.manager.online("gateway-a"))

    async def test_offline_expiry_is_scoped_to_one_gateway(self):
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot)))
        second_boot = str(uuid.uuid4())
        self.manager.start("gateway-b")
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(second_boot, serial="gateway-b")))
        self.manager.runtime["gateway-a"]["seen"] -= 181
        self.manager._expire(None)
        self.assertFalse(self.manager.online("gateway-a"))
        self.assertTrue(self.manager.online("gateway-b"))

    async def test_non_heartbeat_from_stale_boot_is_rejected(self):
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot)))
        stale = inventory(str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError, "stale_session"):
            await self.manager.upload_inventory(DATA.validate_inventory(stale))

    async def test_heartbeat_capabilities_and_authoritative_inventory(self):
        result = await self.online_with_inventory()
        self.assertTrue(self.manager.online("gateway-a"))
        self.assertTrue(self.manager.has_capability("gateway-a", "bluetooth_unpair"))
        self.assertEqual(result["reconciled"], {"created": 1, "updated": 0, "removed": 0})
        empty = inventory(self.boot, sequence=1, devices=[])
        result = await self.manager.upload_inventory(DATA.validate_inventory(empty))
        self.assertEqual(result["reconciled"]["removed"], 1)
        self.assertEqual(self.manager.inventory("gateway-a"), {})

    async def test_learning_remote_is_created_only_after_apk_capability_confirmation(self):
        added = []
        self.manager.register_ir_learning_entity_adder(
            "gateway-a",
            lambda entities, *args: added.extend(entities),
            lambda: LEARNING.IrLearningRemote(self.hass, "gateway-a"),
        )

        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot)))
        self.assertEqual(added, [])

        capable = heartbeat(self.boot, sequence=1)
        capable["payload"]["capabilities"].append("ir_learning_uart")
        await self.manager.heartbeat(DATA.validate_heartbeat(capable))
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]._attr_unique_id, "gateway-a_ir_learning")

        capable["sequence"] = 2
        await self.manager.heartbeat(DATA.validate_heartbeat(capable))
        self.assertEqual(len(added), 1)

    async def test_sequence_retry_is_idempotent_and_conflict_is_rejected(self):
        message = DATA.validate_heartbeat(heartbeat(self.boot))
        first = await self.manager.heartbeat(message)
        retry = dict(message)
        retry["id"] = 99
        self.assertEqual(await self.manager.heartbeat(retry), first)
        conflict = copy.deepcopy(message)
        conflict["payload"]["app_version"] = "other"
        with self.assertRaisesRegex(ValueError, "sequence_conflict"):
            await self.manager.heartbeat(conflict)

    async def test_storage_failure_rolls_back_inventory_and_sequence(self):
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot)))
        self.hass.data["astrion"]["store"].fail = True
        with self.assertRaises(OSError):
            await self.manager.upload_inventory(DATA.validate_inventory(inventory(self.boot)))
        self.assertEqual(self.manager.inventory("gateway-a"), {})
        protocol = self.hass.data["astrion"]["library"]["gateway_runtime_protocol"]
        self.assertNotIn("astrion/bluetooth/inventory", protocol["sequences"].get("gateway-a", {}))

    async def start_learning(self, device="TV", key="power"):
        message = heartbeat(self.boot)
        message["payload"]["capabilities"].append("ir_learning_uart")
        if not self.manager.online("gateway-a"):
            await self.manager.heartbeat(DATA.validate_heartbeat(message))
        entity = LEARNING.IrLearningRemote(self.hass, "gateway-a")
        task = asyncio.create_task(entity.async_learn_command(device=device, command=[key]))
        await asyncio.sleep(0)
        commands = self.hass.data["astrion"]["library"]["gateway_runtime_protocol"]["commands"]
        command_id = next(key for key, item in commands.items() if item["state"] == "pending")
        return task, command_id

    def learning_ack(self, command_id, sequence=0):
        message = envelope("astrion/gateway/ack_command", self.boot, sequence, {
            "command_id": command_id, "command_type": "ir.learn", "command_version": 1,
            "status": "succeeded", "result": {
                "format": "raw", "code": "38000,9000,4500,560",
                "raw_data_hex": "038481c20038ffffffff",
            },
        })
        message["schema_version"] = 2
        return DATA.validate_ack(message)

    async def test_learning_save_duplicate_delete_and_reload(self):
        task, command_id = await self.start_learning()
        self.assertEqual(self.hass.bus.events[-1][1]["gateway_serial"], "gateway-a")
        self.assertFalse(task.done())
        request = envelope("astrion/gateway/get_pending_commands", self.boot, 0, {})
        self.assertEqual((await self.manager.get_pending(DATA.validate_get_pending(request)))["commands"], [])
        request.update(schema_version=2, sequence=1)
        pending = await self.manager.get_pending(DATA.validate_get_pending(request))
        self.assertEqual(pending["commands"][0]["command_id"], command_id)
        await self.manager.ack(self.learning_ack(command_id))
        await task
        stored = copy.deepcopy(self.manager.ir_codes("gateway-a"))
        self.assertEqual(stored["TV"]["power"], {"code": "38000,9000,4500,560"})
        # 新协调器读取公共红外Store，模拟HA重启后的码库恢复。
        restarted = Hass()
        restarted.data["astrion"]["library"] = copy.deepcopy(self.hass.data["astrion"]["store"].saved[-1])
        restarted.data["astrion"]["ir_codes"] = copy.deepcopy(
            self.hass.data["astrion"]["ir_code_store"].saved[-1]
        )
        self.assertEqual(GATEWAY.coordinator(restarted).ir_codes("gateway-a"), stored)
        duplicate = await self.manager.ack(self.learning_ack(command_id, 1))
        self.assertTrue(duplicate["duplicate"])
        # 同名按键重新下发学习，成功后覆盖旧码并保留实际载波频率。
        next_task, next_id = await self.start_learning()
        self.assertNotEqual(next_id, command_id)
        self.assertEqual(self.manager.ir_codes("gateway-a"), stored)
        next_ack = self.learning_ack(next_id, 2)
        next_ack["payload"]["result"]["code"] = "56000,9000,4500,560"
        await self.manager.ack(next_ack)
        await next_task
        stored = copy.deepcopy(self.manager.ir_codes("gateway-a"))
        self.assertEqual(stored["TV"]["power"], {"code": "56000,9000,4500,560"})
        self.assertEqual(self.hass.data["astrion"]["ir_code_store"].saved[-1], stored)
        # 旧任务的重复回执不能把新码覆盖回去。
        await self.manager.ack(self.learning_ack(command_id, 3))
        self.assertEqual(self.manager.ir_codes("gateway-a"), stored)
        entity = LEARNING.IrLearningRemote(self.hass, "gateway-a")
        self.manager.runtime.clear()
        count = len(self.hass.bus.events)
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await entity.async_learn_command(device="TV", command="power")
        self.assertEqual(len(self.hass.bus.events), count)
        self.assertEqual(self.manager.ir_codes("gateway-a"), stored)
        self.assertTrue(entity.available)  # 离线时仍可删除已保存的码。
        await entity.async_delete_command(device="TV", command=["power"])
        self.assertEqual(self.manager.ir_codes("gateway-a"), {})
        self.assertEqual(len(self.hass.bus.events), count)
        # 成功回执重试不能恢复已经删除的按键。
        await self.manager.heartbeat(DATA.validate_heartbeat(heartbeat(self.boot, 1)))
        await self.manager.ack(self.learning_ack(command_id, 4))
        self.assertEqual(self.manager.ir_codes("gateway-a"), {})

    async def test_learning_storage_failure_is_retryable_without_success_or_data_loss(self):
        for sequence, store_name in enumerate(("ir_code_store", "store")):
            with self.subTest(store=store_name):
                old = {"TV": {"power": {"code": "56000,560,560,560"}}}
                self.hass.data["astrion"]["ir_codes"] = copy.deepcopy(old)
                task, command_id = await self.start_learning()
                store = self.hass.data["astrion"][store_name]
                store.fail = True
                with self.assertRaises(OSError):
                    await self.manager.ack(self.learning_ack(command_id, sequence))
                self.assertFalse(task.done())
                self.assertEqual(self.manager.ir_codes("gateway-a"), old)
                self.assertTrue(self.manager.command_active("gateway-a", "ir_learning"))
                if store_name == "store":
                    self.assertEqual(self.hass.data["astrion"]["ir_code_store"].saved[-1], old)
                store.fail = False
                await self.manager.ack(self.learning_ack(command_id, sequence))
                await task
                self.assertEqual(self.manager.ir_codes()["TV"]["power"], {"code": "38000,9000,4500,560"})
        store = self.hass.data["astrion"]["ir_code_store"]
        store.fail = True
        with self.assertRaisesRegex(RuntimeError, "Unable to delete"):
            await self.manager.delete_ir("gateway-a", "TV", ["power"])
        self.assertIn("power", self.manager.ir_codes("gateway-a")["TV"])

    async def test_relearning_failure_and_invalid_result_keep_old_code(self):
        old = {"TV": {"power": {"code": "56000,560,560,560"}}}
        self.hass.data["astrion"]["ir_codes"] = copy.deepcopy(old)
        for sequence, status in enumerate(("failed", "rejected")):
            with self.subTest(status=status):
                task, command_id = await self.start_learning()
                message = self.learning_ack(command_id, sequence)
                message["payload"].pop("result")
                message["payload"].update(status=status, error={
                    "code": "ir_learning_failed", "message": "learning failed", "retryable": False,
                })
                await self.manager.ack(DATA.validate_ack(message))
                with self.assertRaisesRegex(RuntimeError, "learning failed"):
                    await task
                self.assertEqual(self.manager.ir_codes(), old)
        task, command_id = await self.start_learning()
        invalid = self.learning_ack(command_id, 2)
        invalid["payload"]["result"]["code"] = "38000,9001,4500,560"
        with self.assertRaisesRegex(ValueError, "invalid_payload"):
            await self.manager.ack(invalid)
        self.assertEqual(self.manager.ir_codes(), old)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.manager.ir_codes(), old)

    async def test_full_library_allows_relearning_but_rejects_new_entries(self):
        self.hass.data["astrion"]["ir_codes"] = {
            f"device-{index}": {"power": {"code": "38000,560,560,560"}}
            for index in range(GATEWAY.MAX_DEVICES - 1)
        }
        self.manager.ir_codes()["TV"] = {
            key: {"code": "38000,560,560,560"}
            for key in ["power"] + [f"key-{index}" for index in range(GATEWAY.MAX_KEYS - 1)]
        }
        task, command_id = await self.start_learning()
        with self.assertRaisesRegex(RuntimeError, "full"):
            await self.manager.learn_ir("gateway-a", "TV", "new-key")
        with self.assertRaisesRegex(RuntimeError, "full"):
            await self.manager.learn_ir("gateway-a", "new-device", "power")
        await self.manager.ack(self.learning_ack(command_id))
        await task
        self.assertEqual(len(self.manager.ir_codes()), GATEWAY.MAX_DEVICES)
        self.assertEqual(len(self.manager.ir_codes()["TV"]), GATEWAY.MAX_KEYS)
        self.assertEqual(self.manager.ir_codes()["TV"]["power"], {"code": "38000,9000,4500,560"})

    async def test_delete_pending_learning_rejects_late_reply_and_keeps_other_gateway(self):
        task, command_id = await self.start_learning()
        self.hass.data["astrion"]["ir_codes"]["Amp"] = {
            "mute": {"code": "38000,560,560,560"}
        }
        await LEARNING.IrLearningRemote(self.hass, "gateway-a").async_delete_command(device="TV", command="power")
        with self.assertRaisesRegex(RuntimeError, "canceled"):
            await task
        with self.assertRaisesRegex(ValueError, "command_conflict"):
            await self.manager.ack(self.learning_ack(command_id))
        self.assertNotIn("TV", self.manager.ir_codes("gateway-a"))
        self.assertEqual(self.manager.ir_codes("gateway-b")["Amp"]["mute"]["code"], "38000,560,560,560")

    async def test_learning_rejects_busy_wrong_gateway_and_stale_session(self):
        task, command_id = await self.start_learning()
        with self.assertRaisesRegex(RuntimeError, "already learning"):
            await self.manager.learn_ir("gateway-a", "TV", "up")
        self.manager.start("gateway-b")
        other_boot = str(uuid.uuid4())
        other = heartbeat(other_boot, serial="gateway-b")
        other["payload"]["capabilities"].append("ir_learning_uart")
        await self.manager.heartbeat(DATA.validate_heartbeat(other))
        with self.assertRaisesRegex(RuntimeError, "already being learned"):
            await self.manager.learn_ir("gateway-b", "TV", "power")
        wrong = self.learning_ack(command_id)
        wrong.update(gateway_serial="gateway-b", boot_id=other_boot)
        with self.assertRaisesRegex(ValueError, "command_conflict"):
            await self.manager.ack(wrong)
        stale = self.learning_ack(command_id)
        stale["boot_id"] = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, "stale_session"):
            await self.manager.ack(stale)
        await self.manager.delete_ir("gateway-a", "TV", ["power"])
        with self.assertRaises(RuntimeError):
            await task

    async def test_learning_expiry_cancel_and_gateway_removal(self):
        old = {"TV": {"power": {"code": "56000,560,560,560"}}}
        self.hass.data["astrion"]["ir_codes"] = copy.deepcopy(old)
        task, command_id = await self.start_learning()
        command = self.hass.data["astrion"]["library"]["gateway_runtime_protocol"]["commands"][command_id]
        command["expires_at"] = "2000-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "command_conflict"):
            await self.manager.ack(self.learning_ack(command_id))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.manager.ir_codes("gateway-a"), old)
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            await self.manager.learn_ir("gateway-a", "TV", "power", timeout=0.01)
        self.assertEqual(self.manager.ir_codes("gateway-a"), old)
        next_task, next_id = await self.start_learning(key="up")
        await self.manager.remove_gateway("gateway-a")
        with self.assertRaises(RuntimeError):
            await next_task
        self.assertEqual(self.manager.ir_codes("gateway-a"), old)

    async def test_remote_actions_validate_before_dispatch(self):
        entity = LEARNING.IrLearningRemote(self.hass, "gateway-a")
        for kwargs in [
            {}, {"device": "TV", "command": ""}, {"device": "TV", "command": ["power", ""]},
            {"device": "TV", "command": "power", "command_type": "rf"},
            {"device": "TV", "command": "power", "alternative": True},
            {"device": "TV", "command": "power", "timeout": 0},
        ]:
            with self.assertRaises(RuntimeError):
                await entity.async_learn_command(**kwargs)
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await entity.async_learn_command(device="TV", command="power")
        self.assertEqual(self.hass.bus.events, [])


if __name__ == "__main__":
    unittest.main()
