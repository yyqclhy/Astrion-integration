"""Astrion 网关协议 v1 的纯数据校验工具。

本模块不导入 Home Assistant。通信协议与设备清单合并规则不依赖运行环境，
因此无需启动 Home Assistant 即可进行单元测试。
"""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

PROTOCOL_VERSION = 1
SCHEMA_VERSION = 1
PROTOCOL = "bluetooth_hid"
HID_PROFILE = "keyboard_v1"
HID_KEYS = ("hid_keyboard_up", "hid_keyboard_down", "hid_keyboard_left", "hid_keyboard_right")
ADAPTER_STATES = {"on", "off", "turning_on", "turning_off", "unsupported", "unknown"}
PERMISSION_STATES = {"granted", "denied", "unknown"}
CONNECTION_STATES = {"disconnected", "connecting", "connected", "disconnecting", "unknown"}
DEVICE_TYPES = {"classic", "le", "dual", "unknown"}
HID_SUPPORT = {"unknown", "supported", "unsupported"}
COMMAND_STATUSES = {"succeeded", "failed", "rejected"}
COMMAND_ERROR_CODES = {
    "unsupported_command", "invalid_target", "bluetooth_unavailable", "permission_denied",
    "unpair_rejected", "unpair_timeout", "command_expired", "internal_error",
}
MAX_SEQUENCE = 9_007_199_254_740_991
MAX_DEVICES = 100
MAC_PATTERN = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$")


def device_id(address):
    """根据规范化的蓝牙地址返回稳定的资源标识。"""
    return "bt_" + address.replace(":", "").lower()


def _plain_int(value):
    return type(value) is int


def _string(value, minimum=1, maximum=128):
    return isinstance(value, str) and minimum <= len(value) <= maximum


def _uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def validate_envelope(data, expected_type):
    """校验并复制公共请求信封。"""
    required = {
        "id", "type", "protocol_version", "schema_version", "gateway_serial",
        "boot_id", "sequence", "payload",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("invalid_payload")
    if data.get("type") != expected_type:
        raise ValueError("invalid_payload")
    if not _plain_int(data.get("id")) or data["id"] < 1:
        raise ValueError("invalid_payload")
    if not _plain_int(data.get("protocol_version")) or data["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("unsupported_protocol")
    if not _plain_int(data.get("schema_version")) or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported_schema")
    serial = data.get("gateway_serial")
    if not _string(serial) or serial != serial.strip():
        raise ValueError("invalid_payload")
    if not _uuid(data.get("boot_id")):
        raise ValueError("invalid_payload")
    sequence = data.get("sequence")
    if not _plain_int(sequence) or not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("invalid_payload")
    if not isinstance(data.get("payload"), dict):
        raise ValueError("invalid_payload")
    return dict(data)


def request_fingerprint(data):
    """计算业务内容的哈希值，排除仅用于传输关联的 WebSocket id。"""
    logical = {key: value for key, value in data.items() if key != "id"}
    canonical = json.dumps(logical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_heartbeat(data):
    data = validate_envelope(data, "astrion/gateway/heartbeat")
    payload = data["payload"]
    required = {"app_version", "platform", "platform_version", "capabilities"}
    if not required <= set(payload) or set(payload) - required - {"app_build"}:
        raise ValueError("invalid_payload")
    if not _string(payload.get("app_version"), 1, 64) or payload.get("platform") != "android":
        raise ValueError("invalid_payload")
    if not _string(payload.get("platform_version"), 1, 32):
        raise ValueError("invalid_payload")
    if "app_build" in payload and (not _plain_int(payload["app_build"]) or payload["app_build"] < 0):
        raise ValueError("invalid_payload")
    capabilities = payload.get("capabilities")
    if (not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 64
            or len(set(capabilities)) != len(capabilities)):
        raise ValueError("invalid_payload")
    for capability in capabilities:
        if not _string(capability, 1, 64) or not CAPABILITY_PATTERN.fullmatch(capability):
            raise ValueError("invalid_payload")
    return data


def _validate_device(item):
    required = {"bluetooth_address", "name", "bluetooth_type", "connection_state", "hid_support"}
    if not isinstance(item, dict) or set(item) != required:
        raise ValueError("invalid_payload")
    address = item.get("bluetooth_address")
    if not isinstance(address, str):
        raise ValueError("invalid_payload")
    address = address.upper()
    if not MAC_PATTERN.fullmatch(address) or not _string(item.get("name"), 0, 128):
        raise ValueError("invalid_payload")
    if not isinstance(item.get("bluetooth_type"), str) or item.get("bluetooth_type") not in DEVICE_TYPES:
        raise ValueError("invalid_payload")
    if (not isinstance(item.get("connection_state"), str)
            or not isinstance(item.get("hid_support"), str)
            or item.get("connection_state") not in CONNECTION_STATES
            or item.get("hid_support") not in HID_SUPPORT):
        raise ValueError("invalid_payload")
    return {
        "bluetooth_address": address,
        "name": item["name"],
        "bluetooth_type": item["bluetooth_type"],
        "connection_state": item["connection_state"],
        "hid_support": "unsupported" if item["bluetooth_type"] == "le" else item["hid_support"],
    }


def validate_inventory(data):
    data = validate_envelope(data, "astrion/bluetooth/inventory")
    payload = data["payload"]
    if set(payload) - {"adapter_state", "permission_state", "inventory_complete", "devices"}:
        raise ValueError("invalid_payload")
    if payload.get("adapter_state") not in ADAPTER_STATES or payload.get("permission_state") not in PERMISSION_STATES:
        raise ValueError("invalid_payload")
    complete = payload.get("inventory_complete")
    if type(complete) is not bool:
        raise ValueError("invalid_payload")
    normalized = dict(data)
    normalized["payload"] = dict(payload)
    if not complete:
        if "devices" in payload:
            raise ValueError("invalid_payload")
        return normalized
    if payload["adapter_state"] != "on" or payload["permission_state"] != "granted":
        raise ValueError("invalid_payload")
    devices = payload.get("devices")
    if not isinstance(devices, list) or len(devices) > MAX_DEVICES:
        raise ValueError("invalid_payload")
    normalized_devices = []
    seen = set()
    for item in devices:
        device = _validate_device(item)
        if device["bluetooth_address"] in seen:
            raise ValueError("invalid_payload")
        seen.add(device["bluetooth_address"])
        normalized_devices.append(device)
    normalized["payload"]["devices"] = normalized_devices
    return normalized


def validate_get_pending(data):
    data = validate_envelope(data, "astrion/gateway/get_pending_commands")
    if set(data["payload"]) - {"limit"}:
        raise ValueError("invalid_payload")
    limit = data["payload"].get("limit", 20)
    if not _plain_int(limit) or not 1 <= limit <= 20:
        raise ValueError("invalid_payload")
    data["payload"] = {"limit": limit}
    return data


def validate_ack(data):
    data = validate_envelope(data, "astrion/gateway/ack_command")
    payload = data["payload"]
    required = {"command_id", "command_type", "command_version", "status"}
    if not required <= set(payload) or set(payload) - required - {"result", "error"}:
        raise ValueError("invalid_payload")
    if not _uuid(payload.get("command_id")) or payload.get("command_type") != "bluetooth.unpair":
        raise ValueError("invalid_payload")
    if not _plain_int(payload.get("command_version")) or payload["command_version"] != 1:
        raise ValueError("invalid_payload")
    status = payload.get("status")
    if status not in COMMAND_STATUSES:
        raise ValueError("invalid_payload")
    if status == "succeeded":
        if set(payload) != required | {"result"}:
            raise ValueError("invalid_payload")
        result = payload["result"]
        if (not isinstance(result, dict) or set(result) != {"bond_state", "outcome"}
                or result.get("bond_state") != "none"
                or result.get("outcome") not in {"unpaired", "already_unpaired"}):
            raise ValueError("invalid_payload")
    else:
        if set(payload) != required | {"error"}:
            raise ValueError("invalid_payload")
        error = payload["error"]
        if (not isinstance(error, dict) or set(error) != {"code", "message", "retryable"}
                or error.get("code") not in COMMAND_ERROR_CODES
                or not _string(error.get("message"), 1, 512)
                or type(error.get("retryable")) is not bool):
            raise ValueError("invalid_payload")
    return data


def merge_inventory(previous, message):
    """返回权威设备清单及协调过程的变更计数。"""
    # 兼容已停止注册的实验接口。运行代码不再注册该接口，
    # 但保留其纯数据合并工具，避免升级时仍导入此模块的代码失效。
    if "payload" not in message:
        if not message["inventory_complete"]:
            return dict(previous)
        result = {key: {**value, "paired": False} for key, value in previous.items()}
        for item in message["devices"]:
            result[device_id(item["bluetooth_address"])] = {
                "bluetooth_address": item["bluetooth_address"], "name": item["name"],
                "bluetooth_type": item["bluetooth_type"], "paired": True,
            }
        return result
    payload = message["payload"]
    if not payload["inventory_complete"]:
        return dict(previous), {"created": 0, "updated": 0, "removed": 0}
    result = {}
    created = updated = 0
    for item in payload["devices"]:
        key = device_id(item["bluetooth_address"])
        record = {
            "bluetooth_address": item["bluetooth_address"],
            "name": item["name"],
            "bluetooth_type": item["bluetooth_type"],
            "paired": True,
        }
        result[key] = record
        if key not in previous:
            created += 1
        elif previous[key] != record:
            updated += 1
    removed = len(set(previous) - set(result))
    return result, {"created": created, "updated": updated, "removed": removed}


def validate_upload(data):
    """校验已停用的实验版清单结构，仅用于保持源码兼容。"""
    required = {
        "id", "type", "schema_version", "serial_number", "adapter_state",
        "permission_state", "inventory_complete",
    }
    if not required <= set(data) or set(data) - required - {"devices"}:
        raise ValueError("invalid_payload")
    if data.get("type") != "astrion/submit_bluetooth_devices":
        raise ValueError("invalid_payload")
    if not _plain_int(data.get("schema_version")) or data["schema_version"] != 1:
        raise ValueError("unsupported_schema")
    serial = data.get("serial_number")
    if not _string(serial) or serial != serial.strip():
        raise ValueError("invalid_payload")
    envelope = {
        "id": data["id"], "type": "astrion/bluetooth/inventory",
        "protocol_version": 1, "schema_version": 1, "gateway_serial": serial,
        "boot_id": "00000000-0000-0000-0000-000000000000", "sequence": 0,
        "payload": {key: copy for key, copy in data.items() if key in {
            "adapter_state", "permission_state", "inventory_complete", "devices"
        }},
    }
    normalized = validate_inventory(envelope)["payload"]
    return {**data, **normalized}
