"""使用轻量 HA 测试替身验证网关协议 v1 状态机。"""
import copy
import unittest
import uuid

from support import DATA, GATEWAY, Hass


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

    async def test_unpair_requires_success_ack_before_delete(self):
        await self.online_with_inventory()
        command_id = await self.manager.create_unpair("gateway-a", "bt_aabbccddeeff")
        self.assertIn("bt_aabbccddeeff", self.manager.inventory("gateway-a"))
        self.assertFalse(self.manager.can_unpair("gateway-a", "bt_aabbccddeeff"))
        self.assertEqual(self.hass.bus.events[-1][0], "astrion/gateway/command_available")

        request = envelope("astrion/gateway/get_pending_commands", self.boot, 0, {"limit": 20})
        pending = await self.manager.get_pending(DATA.validate_get_pending(request))
        self.assertEqual(pending["commands"][0]["command_id"], command_id)
        self.assertEqual(pending["commands"][0]["delivery_attempt"], 1)
        self.assertIn("bt_aabbccddeeff", self.manager.inventory("gateway-a"))

        ack = envelope("astrion/gateway/ack_command", self.boot, 0, {
            "command_id": command_id,
            "command_type": "bluetooth.unpair",
            "command_version": 1,
            "status": "succeeded",
            "result": {"bond_state": "none", "outcome": "unpaired"},
        })
        result = await self.manager.ack(DATA.validate_ack(ack))
        self.assertFalse(result["duplicate"])
        self.assertNotIn("bt_aabbccddeeff", self.manager.inventory("gateway-a"))

    async def test_failed_ack_keeps_entity_and_complete_inventory_repairs(self):
        await self.online_with_inventory()
        command_id = await self.manager.create_unpair("gateway-a", "bt_aabbccddeeff")
        failed = envelope("astrion/gateway/ack_command", self.boot, 0, {
            "command_id": command_id,
            "command_type": "bluetooth.unpair",
            "command_version": 1,
            "status": "failed",
            "error": {"code": "unpair_timeout", "message": "timeout", "retryable": True},
        })
        await self.manager.ack(DATA.validate_ack(failed))
        self.assertIn("bt_aabbccddeeff", self.manager.inventory("gateway-a"))
        await self.manager.upload_inventory(DATA.validate_inventory(inventory(self.boot, sequence=1, devices=[])))
        self.assertEqual(self.manager.inventory("gateway-a"), {})
        await self.manager.upload_inventory(DATA.validate_inventory(inventory(self.boot, sequence=2)))
        self.assertIn("bt_aabbccddeeff", self.manager.inventory("gateway-a"))

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


if __name__ == "__main__":
    unittest.main()
