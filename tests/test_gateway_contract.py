"""网关协议 v1 的纯数据校验与设备清单协调测试。"""
import base64
import copy
import unittest
import uuid

from support import DATA
from test_gateway_protocol import envelope, heartbeat, inventory


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

    def test_status_requires_v2_and_rejects_unknown_or_out_of_range(self):
        message = envelope("astrion/gateway/status", self.boot, 0, {
            "battery_level": 88, "charging": True, "screen_on": False, "brightness": 200,
        })
        message["schema_version"] = 2
        self.assertEqual(DATA.validate_status(message)["payload"]["battery_level"], 88)
        for payload in (
            {}, {"battery_level": -1}, {"battery_level": 101}, {"charging": "yes"},
            {"screen_on": 1}, {"brightness": 256}, {"unknown": 1},
        ):
            invalid = copy.deepcopy(message)
            invalid["payload"] = payload
            with self.assertRaisesRegex(ValueError, "invalid_payload"):
                DATA.validate_status(invalid)
        legacy = copy.deepcopy(message)
        legacy["schema_version"] = 1
        with self.assertRaisesRegex(ValueError, "unsupported_schema"):
            DATA.validate_status(legacy)

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

    def test_device_ack_requires_v2_and_actual_state(self):
        base = {
            "id": 1, "type": "astrion/gateway/ack_command", "protocol_version": 1,
            "schema_version": 2, "gateway_serial": "gateway-a", "boot_id": self.boot,
            "sequence": 0,
            "payload": {
                "command_id": str(uuid.uuid4()), "command_type": "device.set_brightness",
                "command_version": 1, "status": "succeeded", "result": {"brightness": 128},
            },
        }
        DATA.validate_ack(base)
        legacy = copy.deepcopy(base)
        legacy["schema_version"] = 1
        with self.assertRaises(ValueError):
            DATA.validate_ack(legacy)
        for result in ({"brightness": 256}, {"brightness": -1}, {"brightness": "128"},
                       {}, {"screen_on": True}):
            invalid = copy.deepcopy(base)
            invalid["payload"]["result"] = result
            with self.subTest(result=result), self.assertRaises(ValueError):
                DATA.validate_ack(invalid)
        screen = copy.deepcopy(base)
        screen["payload"].update(command_type="device.screen_off", result={"screen_on": False})
        DATA.validate_ack(screen)
        screen["payload"]["result"] = {"screen_on": 0}
        with self.assertRaises(ValueError):
            DATA.validate_ack(screen)

    def test_media_state_requires_known_fields_and_ranges(self):
        message = envelope("astrion/gateway/media_state", self.boot, 0, {
            "state": "playing", "volume_level": 50, "muted": False,
        })
        self.assertEqual(DATA.validate_media_state(message)["payload"]["state"], "playing")
        paused = copy.deepcopy(message)
        paused["payload"] = {"state": "paused"}
        self.assertEqual(DATA.validate_media_state(paused)["payload"]["state"], "paused")
        for payload in (
            {}, {"volume_level": -1}, {"volume_level": 101},
            {"volume_level": "50"}, {"muted": 0}, {"unknown": 1},
        ):
            invalid = copy.deepcopy(message)
            invalid["payload"] = payload
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "invalid_payload"):
                DATA.validate_media_state(invalid)
        legacy = copy.deepcopy(message)
        legacy["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "unsupported_schema"):
            DATA.validate_media_state(legacy)

    def test_motion_event_accepts_only_known_types(self):
        for event_type in ("picked_up", "placed_down", "motion_detected"):
            message = envelope("astrion/gateway/motion_event", self.boot, 0, {
                "event_type": event_type,
            })
            self.assertEqual(
                DATA.validate_motion_event(message)["payload"]["event_type"], event_type)
        for payload in (
            {}, {"event_type": "unknown"}, {"event_type": "picked_up", "extra": True},
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "invalid_payload"):
                DATA.validate_motion_event(
                    envelope("astrion/gateway/motion_event", self.boot, 0, payload))
        legacy = envelope("astrion/gateway/motion_event", self.boot, 0, {
            "event_type": "picked_up",
        })
        legacy["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "unsupported_schema"):
            DATA.validate_motion_event(legacy)

    def test_media_ack_requires_v2_and_actual_state(self):
        base = {
            "id": 1, "type": "astrion/gateway/ack_command", "protocol_version": 1,
            "schema_version": 2, "gateway_serial": "gateway-a", "boot_id": self.boot,
            "sequence": 0,
        }
        results = {
            "device.play_media": {"state": "playing"},
            "device.stop_media": {"state": "idle"},
            "device.pause_media": {"state": "paused"},
            "device.resume_media": {"state": "playing"},
            "device.set_volume": {"volume": 30},
            "device.set_mute": {"muted": True},
        }
        for command_type, result in results.items():
            message = copy.deepcopy(base)
            message["payload"] = {
                "command_id": str(uuid.uuid4()), "command_type": command_type,
                "command_version": 1, "status": "succeeded", "result": result,
            }
            DATA.validate_ack(message)
            legacy = copy.deepcopy(message)
            legacy["schema_version"] = 1
            with self.subTest(command_type=command_type), self.assertRaises(ValueError):
                DATA.validate_ack(legacy)
        invalid = copy.deepcopy(base)
        invalid["payload"] = {
            "command_id": str(uuid.uuid4()), "command_type": "device.set_mute",
            "command_version": 1, "status": "succeeded", "result": {"muted": "true"},
        }
        with self.assertRaises(ValueError):
            DATA.validate_ack(invalid)

    def test_assist_routes_validate_session_and_audio(self):
        session_id = str(uuid.uuid4())
        for route, validator, payload in (
            ("astrion/assist/session_start", DATA.validate_assist_session_start,
             {"session_id": session_id}),
            ("astrion/assist/session_end", DATA.validate_assist_session_end,
             {"session_id": session_id}),
            ("astrion/assist/tts_finished", DATA.validate_assist_tts_finished,
             {"session_id": session_id}),
            ("astrion/assist/audio_chunk", DATA.validate_assist_audio_chunk,
             {"session_id": session_id, "audio": base64.b64encode(b"\x00\x01" * 1600).decode()}),
        ):
            validator(envelope(route, self.boot, 0, payload))
            invalid = envelope(route, self.boot, 0, {**payload, "session_id": "announce-1"})
            with self.subTest(route=route), self.assertRaisesRegex(ValueError, "invalid_payload"):
                validator(invalid)
        for audio in ("", "not-base64", base64.b64encode(b"\x00" * 3).decode(),
                      base64.b64encode(b"\x00" * 3202).decode()):
            invalid = envelope("astrion/assist/audio_chunk", self.boot, 0, {
                "session_id": session_id, "audio": audio,
            })
            with self.subTest(audio=audio), self.assertRaisesRegex(ValueError, "invalid_payload"):
                DATA.validate_assist_audio_chunk(invalid)

    def test_learning_ack_requires_v2_and_consistent_uart_pulses(self):
        valid = {
            "id": 1, "type": "astrion/gateway/ack_command", "protocol_version": 1,
            "schema_version": 2, "gateway_serial": "gateway-a", "boot_id": self.boot, "sequence": 0,
            "payload": {
                "command_id": str(uuid.uuid4()), "command_type": "ir.learn", "command_version": 1,
                "status": "succeeded", "result": {
                    "format": "raw", "code": "38000,9000,4500,560",
                    "raw_data_hex": "038481c20038ffffffff",
                },
            },
        }
        DATA.validate_ack(valid)
        legacy = copy.deepcopy(valid)
        legacy["schema_version"] = 1
        with self.assertRaises(ValueError):
            DATA.validate_ack(legacy)
        for replacement in [
            {"simulated": False}, {"format": "broadlink"}, {"code": "38000,-1,4500,560"},
            {"code": "38000,9001,4500,560"}, {"code": "38000,9000,4500"},
            {"raw_data_hex": "838481c20038ffffffff"},
            {"raw_data_hex": "038481c20038ffffff"}, {"extra": 1},
        ]:
            invalid = copy.deepcopy(valid)
            invalid["payload"]["result"].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                DATA.validate_ack(invalid)

        marked = copy.deepcopy(valid)
        marked["payload"]["result"] = {
            "format": "raw", "code": "56000,9000,4500,560,560",
            "raw_data_hex": "00009999038481c20000999900388038ffffffff",
        }
        DATA.validate_ack(marked)
        marked["payload"]["result"] = {
            "format": "raw", "code": "56000,1120,1120,560",
            "raw_data_hex": "0000999900389999003880380000999980380038ffffffff",
        }
        DATA.validate_ack(marked)
        marked["payload"]["result"]["code"] = "56000,560,4500,560"
        marked["payload"]["result"]["raw_data_hex"] = "003881c2003800009999ffffffff"
        with self.assertRaises(ValueError):
            DATA.validate_ack(marked)


if __name__ == "__main__":
    unittest.main()
