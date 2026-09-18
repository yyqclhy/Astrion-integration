"""校验HA学习参数及APK上报的真实红外业务数据。"""
from __future__ import annotations

MAX_DEVICES = 100
MAX_KEYS = 200
MAX_PULSES = 4096


def validate_names(device, commands):
    """使用HA标准动作的字符串或命令列表参数。"""
    def valid_name(value):
        return isinstance(value, str) and 1 <= len(value) <= 128 and value == value.strip()

    if isinstance(commands, str):
        commands = [commands]
    if (not valid_name(device) or not isinstance(commands, list)
            or not 1 <= len(commands) <= MAX_KEYS or not all(valid_name(key) for key in commands)):
        raise ValueError("Specify a device and one or more non-empty command names (max 128 characters)")
    return device, list(dict.fromkeys(commands))


def validate_raw_code(code):
    """沿用APK的频率、高电平时长、低电平时长格式。"""
    if not isinstance(code, str) or not 1 <= len(code) <= 32768:
        raise ValueError("invalid_ir_code")
    parts = code.split(",")
    if not 4 <= len(parts) <= MAX_PULSES + 1 or any(
        not part.isascii() or not part.isdigit() or len(part) > 7 for part in parts
    ):
        raise ValueError("invalid_ir_code")
    values = [int(part) for part in parts]
    if not 20000 <= values[0] <= 60000 or any(not 1 <= value <= 327670 for value in values[1:]):
        raise ValueError("invalid_ir_code")
    if sum(values[1:]) > 2000000:
        raise ValueError("invalid_ir_code")
    return values


def validate_learning_result(result):
    """UART帧校验由APK完成；此处校验实际码及原始时序的一致性。"""
    if (not isinstance(result, dict)
            or set(result) != {"format", "code", "raw_data_hex"}
            or result["format"] != "raw"):
        raise ValueError("invalid_payload")
    try:
        values = validate_raw_code(result["code"])
        raw_hex = result["raw_data_hex"]
        if (not isinstance(raw_hex, str) or len(raw_hex) != (len(values) - 1) * 4 + 8
                or len(raw_hex) > MAX_PULSES * 4 + 8):
            raise ValueError("invalid_payload")
        raw = bytes.fromhex(raw_hex)
        if len(raw) * 2 != len(raw_hex) or raw[-4:] != b"\xff\xff\xff\xff" or values[0] != 38000:
            raise ValueError("invalid_payload")
        for index, duration in enumerate(values[1:]):
            word = int.from_bytes(raw[index * 2:index * 2 + 2], "big")
            if bool(word & 0x8000) != (index % 2 == 0) or (word & 0x7fff) * 10 != duration:
                raise ValueError("invalid_payload")
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("invalid_payload") from error
    return result


def validate_ir_library(library):
    """校验公共红外码库，避免损坏的存储内容进入实体和卡片。"""
    if not isinstance(library, dict) or len(library) > MAX_DEVICES:
        raise ValueError("invalid_ir_library")
    for device, keys in library.items():
        validate_names(device, list(keys) if isinstance(keys, dict) else None)
        if not keys or len(keys) > MAX_KEYS:
            raise ValueError("invalid_ir_library")
        for record in keys.values():
            if not isinstance(record, dict):
                raise ValueError("invalid_ir_library")
            validate_raw_code(record.get("code"))
    return library
