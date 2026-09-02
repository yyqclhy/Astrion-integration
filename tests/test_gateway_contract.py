"""网关协议 v1 的纯数据校验与设备清单协调测试。"""
import copy
import unittest
import uuid

from support import DATA
from test_gateway_protocol import heartbeat, inventory


class GatewayContractTests(unittest.TestCase):
    def setUp(self):
        self.boot = str(uuid.uuid4())

    def test_normalizes_address_and_stable_resource_id(self):
        message = inventory(self.boot)
        message["payload"]["devices"][0]["bluetooth_address"] = "aa:bb:cc:dd:ee:ff"
        normalized = DATA.validate_inventory(message)
        address = normalized["payload"]["devices"][0]["bluetooth_address"]
        self.assertEqual(address, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(DATA.device_id(address), "bt_aabbccddeeff")

    def test_invalid_envelope_and_duplicate_devices_are_rejected(self):
        invalid = heartbeat(self.boot)
        invalid["protocol_version"] = True
        with self.assertRaisesRegex(ValueError, "unsupported_protocol"):
            DATA.validate_heartbeat(invalid)
        duplicate = inventory(self.boot)
        duplicate["payload"]["devices"].append(copy.deepcopy(duplicate["payload"]["devices"][0]))
        duplicate["payload"]["devices"][1]["bluetooth_address"] = "aa:bb:cc:dd:ee:ff"
        with self.assertRaisesRegex(ValueError, "invalid_payload"):
            DATA.validate_inventory(duplicate)

    def test_incomplete_inventory_cannot_delete_or_include_devices(self):
        message = inventory(self.boot)
        message["payload"] = {
            "adapter_state": "off", "permission_state": "granted",
            "inventory_complete": False,
        }
        normalized = DATA.validate_inventory(message)
        previous = {"bt_aabbccddeeff": {"name": "TV", "paired": True}}
        merged, changes = DATA.merge_inventory(previous, normalized)
        self.assertEqual(merged, previous)
        self.assertEqual(changes, {"created": 0, "updated": 0, "removed": 0})
        message["payload"]["devices"] = []
        with self.assertRaisesRegex(ValueError, "invalid_payload"):
            DATA.validate_inventory(message)

    def test_ble_cannot_claim_classic_hid_support(self):
        message = inventory(self.boot)
        message["payload"]["devices"][0].update(bluetooth_type="le", hid_support="supported")
        normalized = DATA.validate_inventory(message)
        self.assertEqual(normalized["payload"]["devices"][0]["hid_support"], "unsupported")

    def test_ack_requires_result_only_for_success(self):
        base = {
            "id": 1, "type": "astrion/gateway/ack_command", "protocol_version": 1,
            "schema_version": 1, "gateway_serial": "gateway-a", "boot_id": self.boot,
            "sequence": 0,
        }
        success = {**base, "payload": {
            "command_id": str(uuid.uuid4()), "command_type": "bluetooth.unpair",
            "command_version": 1, "status": "succeeded",
            "result": {"bond_state": "none", "outcome": "already_unpaired"},
        }}
        DATA.validate_ack(success)
        invalid = copy.deepcopy(success)
        invalid["payload"]["error"] = {
            "code": "internal_error", "message": "wrong branch", "retryable": False,
        }
        with self.assertRaisesRegex(ValueError, "invalid_payload"):
            DATA.validate_ack(invalid)


if __name__ == "__main__":
    unittest.main()
