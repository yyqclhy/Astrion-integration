"""Astrion 网关协议 v1 的运行时协调器及 WebSocket 处理入口。"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import logging
from time import monotonic
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .bluetooth_data import (
    device_id,
    merge_inventory,
    request_fingerprint,
    validate_ack,
    validate_get_pending,
    validate_heartbeat,
    validate_inventory,
)
from .const import DOMAIN
from .ir_learning_data import MAX_DEVICES, MAX_KEYS, validate_learning_result, validate_names

HEARTBEAT_INTERVAL = 60
ONLINE_TIMEOUT = 180
EXPIRY_INTERVAL = 30
UNPAIR_EXPIRY = 120
TERMINAL_RETENTION = 24 * 60 * 60
COMMAND_EVENT = f"{DOMAIN}/gateway/command_available"
TERMINAL_STATES = {"succeeded", "failed", "rejected", "expired", "canceled"}
_LOGGER = logging.getLogger(__name__)


def signal(serial):
    """供各个依赖网关的实体平台共用的分发信号。"""
    return f"{DOMAIN}_gateway_{serial}"


def coordinator(hass):
    shared = hass.data.setdefault(DOMAIN, {})
    if "gateway_protocol" not in shared:
        shared["gateway_protocol"] = GatewayCoordinator(hass)
    return shared["gateway_protocol"]


async def _async_remove_orphan_bluetooth_devices(hass, identifiers):
    """蓝牙子设备的最后一个实体消失后，移除该子设备。

    Remote 与取消配对按钮共用一条设备注册表记录，因此必须等两条实体注册表记录
    都已移除后，才能删除设备。DOMAIN 检查也用于在传入异常标识时，
    防止清理操作触及网关或其他集成的设备。
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    for identifier in identifiers or set():
        if len(identifier) != 2 or identifier[0] != DOMAIN:
            continue
        device = device_registry.async_get_device(identifiers={identifier})
        if device is None:
            continue
        remaining = er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        )
        if remaining:
            continue
        device_registry.async_remove_device(device.id)
        _LOGGER.info("Removed orphan Bluetooth device registry entry %s", identifier[1])


async def async_remove_bluetooth_entity(hass, entity, entity_domain):
    """移除运行中的蓝牙实体、其注册表记录，以及已无实体关联的子设备。"""
    from homeassistant.helpers import entity_registry as er

    # 在 async_remove() 将实体从 HA 分离之前，记录其注册表标识。
    entity_id = getattr(entity, "entity_id", None)
    unique_id = getattr(entity, "_attr_unique_id", None)
    device_info = getattr(entity, "_attr_device_info", None) or {}
    identifiers = set(device_info.get("identifiers", set()))

    if getattr(entity, "hass", None) is not None:
        await entity.async_remove()

    registry = er.async_get(hass)
    if not entity_id and unique_id:
        entity_id = registry.async_get_entity_id(entity_domain, DOMAIN, unique_id)
    if entity_id and registry.async_get(entity_id):
        registry.async_remove(entity_id)
    await _async_remove_orphan_bluetooth_devices(hass, identifiers)


async def async_reconcile_bluetooth_registry(hass, serial, inventory):
    """清理旧版集成遗留的过期蓝牙注册表记录。

    成功获取的完整设备清单是权威依据。只处理属于当前网关的蓝牙 Remote 与
    取消配对按钮的唯一标识；网关实体、红外实体，以及其他网关的蓝牙子设备
    均不在此次清理范围内。
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    prefix = f"{serial}_bluetooth_"
    expected_device_ids = {
        f"{prefix}{key[3:] if key.startswith('bt_') else key}" for key in inventory
    }
    entity_registry = er.async_get(hass)

    # 先移除过期实体记录，否则检查设备注册表时，其所属的蓝牙设备
    # 仍有关联实体，不应被视为可清理的孤立设备。
    for entry in list(entity_registry.entities.values()):
        unique_id = getattr(entry, "unique_id", "")
        entity_domain = getattr(entry, "domain", entry.entity_id.split(".", 1)[0])
        if (
            getattr(entry, "platform", None) != DOMAIN
            or entity_domain not in {"remote", "button"}
            or not unique_id.startswith(prefix)
        ):
            continue
        device_unique_id = unique_id[:-7] if unique_id.endswith("_unpair") else unique_id
        if device_unique_id not in expected_device_ids:
            entity_registry.async_remove(entry.entity_id)

    device_registry = dr.async_get(hass)
    stale_identifiers = set()
    for device in list(device_registry.devices.values()):
        for identifier in device.identifiers:
            if (
                len(identifier) == 2
                and identifier[0] == DOMAIN
                and identifier[1].startswith(prefix)
                and identifier[1] not in expected_device_ids
            ):
                stale_identifiers.add(identifier)
    await _async_remove_orphan_bluetooth_devices(hass, stale_identifiers)


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(value=None):
    value = value or _utc_now()
    return value.isoformat().replace("+00:00", "Z")


def _parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _protocol_store(library):
    data = library.setdefault("gateway_runtime_protocol", {})
    data.setdefault("commands", {})
    data.setdefault("sequences", {})
    data.setdefault("inventory_revisions", {})
    return data


class GatewayCoordinator:
    """协调网关在线有效期、持久化命令及权威设备清单。"""

    def __init__(self, hass):
        self.hass = hass
        self.active = set()
        self.runtime = {}
        self.lock = asyncio.Lock()
        self._unsub = None
        self._ir_waiters = {}
        # 记录每个配置条目的实体添加回调。学习实体只有收到APK能力确认后才创建。
        self._ir_learning_entity_adders = {}
        self._ir_learning_entities = set()

    def start(self, serial):
        if not serial:
            return
        self.active.add(serial)
        if self._unsub is None:
            self._unsub = async_track_time_interval(
                self.hass, self._expire, timedelta(seconds=EXPIRY_INTERVAL)
            )

    def stop(self, serial):
        self.active.discard(serial)
        self.runtime.pop(serial, None)
        self._ir_learning_entity_adders.pop(serial, None)
        self._ir_learning_entities.discard(serial)
        for command_id, (gateway_serial, event) in tuple(self._ir_waiters.items()):
            if gateway_serial == serial:
                event.set()
        self._notify(serial)
        if not self.active and self._unsub is not None:
            self._unsub()
            self._unsub = None

    def _notify(self, serial):
        try:
            async_dispatcher_send(self.hass, signal(serial))
        except Exception:
            _LOGGER.exception("Gateway entity update failed for %s", serial)

    @callback
    def _expire(self, now):
        for serial in tuple(self.active):
            state = self.runtime.get(serial)
            if state and monotonic() - state.get("seen", 0) > ONLINE_TIMEOUT and not state.get("expired"):
                state["expired"] = True
                self._notify(serial)

    def inventory(self, serial):
        return self.hass.data[DOMAIN].get("library", {}).get("bluetooth_devices", {}).get(serial, {})

    def live(self, serial):
        state = self.runtime.get(serial, {})
        if not state or state.get("expired") or monotonic() - state.get("seen", 0) > ONLINE_TIMEOUT:
            return {}
        return state

    def online(self, serial):
        return bool(self.live(serial))

    def has_capability(self, serial, capability):
        return capability in self.live(serial).get("capabilities", set())

    def register_ir_learning_entity_adder(self, serial, async_add_entities, entity_factory):
        """注册学习实体添加回调；只有APK声明UART能力时才立即创建。"""
        if not serial:
            return
        self._ir_learning_entity_adders[serial] = (async_add_entities, entity_factory)
        self._add_ir_learning_entity_if_supported(serial)

    def unregister_ir_learning_entity_adder(self, serial, async_add_entities=None):
        """注销配置条目的学习实体添加回调，避免卸载后继续添加实体。"""
        registered = self._ir_learning_entity_adders.get(serial)
        if async_add_entities is None or (registered and registered[0] is async_add_entities):
            self._ir_learning_entity_adders.pop(serial, None)
            self._ir_learning_entities.discard(serial)

    def _add_ir_learning_entity_if_supported(self, serial):
        """根据最近心跳能力按需创建一个学习实体，并防止重复添加。"""
        if serial in self._ir_learning_entities or not self.has_capability(serial, "ir_learning_uart"):
            return
        registered = self._ir_learning_entity_adders.get(serial)
        if registered is None:
            return
        async_add_entities, entity_factory = registered
        async_add_entities([entity_factory()], True)
        self._ir_learning_entities.add(serial)

    def command_active(self, serial, resource_id):
        library = self.hass.data[DOMAIN].get("library", {})
        commands = _protocol_store(library)["commands"]
        return any(
            command.get("gateway_serial") == serial
            and command.get("state") not in TERMINAL_STATES
            and command.get("target", {}).get("resource_id") == resource_id
            for command in commands.values()
        )

    def can_unpair(self, serial, resource_id):
        device = self.inventory(serial).get(resource_id)
        live = self.live(serial)
        return bool(
            device and device.get("paired")
            and "bluetooth_unpair" in live.get("capabilities", set())
            and "bluetooth_inventory" in live.get("capabilities", set())
            and live.get("adapter_state") == "on"
            and live.get("permission_state") == "granted"
            and not self.command_active(serial, resource_id)
        )

    def _check_gateway(self, serial):
        if serial not in self.active:
            raise ValueError("unknown_gateway")

    def _check_session(self, message, heartbeat=False):
        self._check_gateway(message["gateway_serial"])
        if heartbeat:
            return
        live = self.live(message["gateway_serial"])
        if not live:
            raise ValueError("gateway_not_ready")
        if live.get("boot_id") != message["boot_id"]:
            raise ValueError("stale_session")

    def _sequence(self, protocol, message, route):
        serial = message["gateway_serial"]
        fingerprint = request_fingerprint(message)
        routes = protocol["sequences"].setdefault(serial, {})
        previous = routes.get(route)
        if previous and previous.get("boot_id") == message["boot_id"]:
            if message["sequence"] < previous["sequence"]:
                raise ValueError("stale_sequence")
            if message["sequence"] == previous["sequence"]:
                if fingerprint != previous.get("fingerprint"):
                    raise ValueError("sequence_conflict")
                return previous.get("result")
        return None

    def _record_sequence(self, protocol, message, route, result):
        protocol["sequences"].setdefault(message["gateway_serial"], {})[route] = {
            "boot_id": message["boot_id"],
            "sequence": message["sequence"],
            "fingerprint": request_fingerprint(message),
            "result": copy.deepcopy(result),
        }

    async def _save(self):
        await self.hass.data[DOMAIN]["store"].async_save(self.hass.data[DOMAIN]["library"])

    def _pending_count(self, protocol, serial):
        return sum(
            command.get("gateway_serial") == serial and command.get("state") not in TERMINAL_STATES
            for command in protocol["commands"].values()
        )

    def _expire_commands(self, protocol):
        now = _utc_now()
        changed = False
        for command in protocol["commands"].values():
            if command.get("state") not in TERMINAL_STATES and _parse(command["expires_at"]) <= now:
                command["state"] = "expired"
                command["updated_at"] = _iso(now)
                changed = True
        cutoff = now - timedelta(seconds=TERMINAL_RETENTION)
        removable = [
            command_id for command_id, command in protocol["commands"].items()
            if command.get("state") in TERMINAL_STATES
            and _parse(command.get("updated_at", command["created_at"])) < cutoff
        ]
        for command_id in removable:
            protocol["commands"].pop(command_id, None)
            changed = True
        return changed

    async def heartbeat(self, message):
        route = message["type"]
        serial = message["gateway_serial"]
        async with self.lock:
            self._check_session(message, heartbeat=True)
            library = self.hass.data[DOMAIN]["library"]
            protocol = _protocol_store(library)
            before = copy.deepcopy(protocol)
            duplicate = self._sequence(protocol, message, route)
            if duplicate is None:
                self._expire_commands(protocol)
                result = {
                    "accepted": True,
                    "server_time": _iso(),
                    "heartbeat_interval_seconds": HEARTBEAT_INTERVAL,
                    "offline_after_seconds": ONLINE_TIMEOUT,
                    "pending_command_count": self._pending_count(protocol, serial),
                }
                self._record_sequence(protocol, message, route, result)
                try:
                    await self._save()
                except Exception:
                    library["gateway_runtime_protocol"] = before
                    raise
            else:
                result = duplicate
            previous_live = self.runtime.get(serial, {})
            self.runtime[serial] = {
                "seen": monotonic(),
                "expired": False,
                "boot_id": message["boot_id"],
                "capabilities": set(message["payload"]["capabilities"]),
                "app_version": message["payload"]["app_version"],
                "platform_version": message["payload"]["platform_version"],
                "adapter_state": previous_live.get("adapter_state", "unknown"),
                "permission_state": previous_live.get("permission_state", "unknown"),
                "devices": previous_live.get("devices", {}),
            }
        self._add_ir_learning_entity_if_supported(serial)
        self._notify(serial)
        return result

    async def upload_inventory(self, message):
        route = message["type"]
        serial = message["gateway_serial"]
        async with self.lock:
            self._check_session(message)
            shared = self.hass.data[DOMAIN]
            library = shared["library"]
            protocol = _protocol_store(library)
            duplicate = self._sequence(protocol, message, route)
            if duplicate is not None:
                return duplicate
            all_inventory = library.setdefault("bluetooth_devices", {})
            existed = serial in all_inventory
            before_inventory = copy.deepcopy(all_inventory.get(serial, {}))
            before_protocol = copy.deepcopy(protocol)
            after, reconciled = merge_inventory(before_inventory, message)
            if message["payload"]["inventory_complete"]:
                all_inventory[serial] = after
            revision = protocol["inventory_revisions"].get(serial, 0) + 1
            protocol["inventory_revisions"][serial] = revision
            result = {
                "accepted": True,
                "inventory_complete": message["payload"]["inventory_complete"],
                "device_count": len(after),
                "inventory_revision": revision,
                "reconciled": reconciled,
            }
            self._record_sequence(protocol, message, route, result)
            try:
                await self._save()
            except Exception:
                library["gateway_runtime_protocol"] = before_protocol
                if existed:
                    all_inventory[serial] = before_inventory
                else:
                    all_inventory.pop(serial, None)
                raise
            payload = message["payload"]
            live = self.runtime[serial]
            live["adapter_state"] = payload["adapter_state"]
            live["permission_state"] = payload["permission_state"]
            if payload["inventory_complete"]:
                live["devices"] = {device_id(item["bluetooth_address"]): item for item in payload["devices"]}
            elif payload["adapter_state"] != "on" or payload["permission_state"] != "granted":
                live["devices"] = {}
        self._notify(serial)
        return result

    async def create_unpair(self, serial, resource_id):
        """先持久化取消配对命令，再发送可能丢失的唤醒事件。"""
        async with self.lock:
            if not self.can_unpair(serial, resource_id):
                raise HomeAssistantError("Bluetooth unpair is unavailable for this gateway or device")
            shared = self.hass.data[DOMAIN]
            library = shared["library"]
            protocol = _protocol_store(library)
            before = copy.deepcopy(protocol)
            now = _utc_now()
            target = self.inventory(serial)[resource_id]
            command_id = str(uuid4())
            protocol["commands"][command_id] = {
                "command_id": command_id,
                "gateway_serial": serial,
                "command_type": "bluetooth.unpair",
                "command_version": 1,
                "state": "pending",
                "created_at": _iso(now),
                "updated_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=UNPAIR_EXPIRY)),
                "delivery_attempt": 0,
                "target": {
                    "resource_type": "bluetooth_device",
                    "resource_id": resource_id,
                    "bluetooth_address": target["bluetooth_address"],
                },
                "parameters": {},
            }
            try:
                await self._save()
            except Exception:
                library["gateway_runtime_protocol"] = before
                raise HomeAssistantError("Unable to persist Bluetooth unpair command")
            count = self._pending_count(protocol, serial)
        self.hass.bus.async_fire(COMMAND_EVENT, {
            "protocol_version": 1,
            "schema_version": 1,
            "gateway_serial": serial,
            "pending_command_count": count,
        })
        self._notify(serial)
        return command_id

    def ir_codes(self, serial=None):
        """所有HA100学习实体读取同一个红外码库。"""
        return self.hass.data[DOMAIN].setdefault("ir_codes", {})

    async def _save_ir_codes(self):
        store = self.hass.data[DOMAIN].get("ir_code_store")
        if store is None:
            raise HomeAssistantError("IR code storage is not initialized")
        await store.async_save(self.ir_codes())

    async def learn_ir(self, serial, device, key, timeout=30):
        """持久化定向学习任务，仅在HA完成保存后返回成功。"""
        try:
            validate_names(device, [key])
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        async with self.lock:
            self._check_gateway(serial)
            existing = self.ir_codes(serial).get(device, {}).get(key)
            if existing is not None:
                return copy.deepcopy(existing)  # 同设备同按键保留原码。
            if not self.has_capability(serial, "ir_learning_uart"):
                raise HomeAssistantError("HA100 is offline or does not support UART IR learning")
            codes = self.ir_codes(serial)
            if (device not in codes and len(codes) >= MAX_DEVICES) or len(codes.get(device, {})) >= MAX_KEYS:
                raise HomeAssistantError("Learned IR library is full")
            library = self.hass.data[DOMAIN]["library"]
            protocol = _protocol_store(library)
            before = copy.deepcopy(protocol)
            self._expire_commands(protocol)
            if self.command_active(serial, "ir_learning"):
                raise HomeAssistantError("This HA100 is already learning an IR command")
            command_id = str(uuid4())
            now = _utc_now()
            protocol["commands"][command_id] = {
                "command_id": command_id, "gateway_serial": serial,
                "command_type": "ir.learn", "command_version": 1,
                "state": "pending", "created_at": _iso(now), "updated_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=timeout)),
                "delivery_attempt": 0,
                "target": {"resource_type": "ir_learning", "resource_id": "ir_learning"},
                "parameters": {"device": device, "command": key, "mode": "uart"},
            }
            try:
                await self._save()
            except Exception as error:
                library["gateway_runtime_protocol"] = before
                raise HomeAssistantError("Unable to persist IR learning command") from error
            event = asyncio.Event()
            self._ir_waiters[command_id] = (serial, event)
            count = self._pending_count(protocol, serial)
        self._notify(serial)
        try:
            self.hass.bus.async_fire(COMMAND_EVENT, {
                "protocol_version": 1, "schema_version": 1,
                "gateway_serial": serial, "pending_command_count": count,
            })
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except asyncio.TimeoutError as error:
                raise HomeAssistantError("IR learning timed out") from error
            command = _protocol_store(self.hass.data[DOMAIN]["library"])["commands"].get(command_id, {})
            if command.get("state") != "succeeded":
                message = command.get("ack", {}).get("error", {}).get("message", "IR learning canceled or gateway unloaded")
                raise HomeAssistantError(message)
            return copy.deepcopy(command["ack"]["result"])
        finally:
            self._ir_waiters.pop(command_id, None)
            # 动作取消后终止任务，避免后续回复重新保存已取消的按键。
            async with self.lock:
                library = self.hass.data[DOMAIN]["library"]
                protocol = _protocol_store(library)
                command = protocol["commands"].get(command_id)
                if command and command["state"] not in TERMINAL_STATES:
                    before = copy.deepcopy(protocol)
                    command["state"] = "expired" if _parse(command["expires_at"]) <= _utc_now() else "canceled"
                    command["updated_at"] = _iso()
                    try:
                        await self._save()
                    except Exception:
                        library["gateway_runtime_protocol"] = before
                        raise
            self._notify(serial)

    async def delete_ir(self, serial, device, keys):
        """HA标准删除动作只修改码库，不下发APK删除命令。"""
        async with self.lock:
            self._check_gateway(serial)
            library = self.hass.data[DOMAIN]["library"]
            all_codes = self.ir_codes()
            before_codes = copy.deepcopy(all_codes)
            protocol = _protocol_store(library)
            before_protocol = copy.deepcopy(protocol)
            codes = all_codes.get(device, {})
            for key in keys:
                codes.pop(key, None)
            if not codes:
                all_codes.pop(device, None)
            canceled = []
            for command_id, command in protocol["commands"].items():
                if (command.get("command_type") == "ir.learn"
                        and command.get("state") not in TERMINAL_STATES
                        and command["parameters"]["device"] == device
                        and command["parameters"]["command"] in keys):
                    command["state"] = "canceled"
                    command["updated_at"] = _iso()
                    canceled.append(command_id)
            try:
                await self._save_ir_codes()
                await self._save()
            except Exception as error:
                shared = self.hass.data[DOMAIN]
                shared["ir_codes"] = before_codes
                library["gateway_runtime_protocol"] = before_protocol
                try:
                    await self._save_ir_codes()
                except Exception:
                    pass
                raise HomeAssistantError("Unable to delete learned IR commands") from error
            for command_id in canceled:
                waiter = self._ir_waiters.get(command_id)
                if waiter:
                    waiter[1].set()
        self._notify(serial)

    async def get_pending(self, message):
        route = message["type"]
        serial = message["gateway_serial"]
        async with self.lock:
            self._check_session(message)
            library = self.hass.data[DOMAIN]["library"]
            protocol = _protocol_store(library)
            before = copy.deepcopy(protocol)
            duplicate = self._sequence(protocol, message, route)
            if duplicate is not None:
                return duplicate
            self._expire_commands(protocol)
            candidates = [
                command for command in protocol["commands"].values()
                if command.get("gateway_serial") == serial
                and command.get("state") in {"pending", "dispatched"}
                and (message["schema_version"] == 2 or command.get("command_type") == "bluetooth.unpair")
            ]
            candidates.sort(key=lambda item: item["created_at"])
            selected = candidates[:message["payload"]["limit"]]
            wire = []
            for command in selected:
                command["state"] = "dispatched"
                command["delivery_attempt"] += 1
                command["updated_at"] = _iso()
                wire.append({key: copy.deepcopy(command[key]) for key in (
                    "command_id", "command_type", "command_version", "created_at", "expires_at",
                    "delivery_attempt", "target", "parameters",
                )})
            result = {
                "accepted": True,
                "server_time": _iso(),
                "commands": wire,
                "remaining_count": max(0, len(candidates) - len(selected)),
            }
            self._record_sequence(protocol, message, route, result)
            try:
                await self._save()
            except Exception:
                library["gateway_runtime_protocol"] = before
                raise
        self._notify(serial)
        return result

    async def ack(self, message):
        route = message["type"]
        serial = message["gateway_serial"]
        payload = message["payload"]
        async with self.lock:
            self._check_session(message)
            shared = self.hass.data[DOMAIN]
            library = shared["library"]
            protocol = _protocol_store(library)
            duplicate_sequence = self._sequence(protocol, message, route)
            if duplicate_sequence is not None:
                return duplicate_sequence
            command = protocol["commands"].get(payload["command_id"])
            if not command:
                raise ValueError("command_not_found")
            if command.get("gateway_serial") != serial:
                raise ValueError("command_conflict")
            if command.get("command_type") != payload["command_type"] or command.get("command_version") != payload["command_version"]:
                raise ValueError("command_conflict")
            if command.get("state") in TERMINAL_STATES:
                if command.get("ack") != payload:
                    raise ValueError("command_conflict")
                result = {
                    "accepted": True, "command_id": payload["command_id"],
                    "command_state": payload["status"], "duplicate": True,
                }
            else:
                if _parse(command["expires_at"]) <= _utc_now():
                    command["state"] = "expired"
                    command["updated_at"] = _iso()
                    await self._save()
                    raise ValueError("command_conflict")
                if payload["command_type"] == "ir.learn" and payload["status"] == "succeeded":
                    validate_learning_result(payload["result"])
                before_protocol = copy.deepcopy(protocol)
                before_codes = copy.deepcopy(self.ir_codes())
                all_inventory = library.setdefault("bluetooth_devices", {})
                before_inventory = copy.deepcopy(all_inventory.get(serial, {}))
                command["state"] = payload["status"]
                command["ack"] = copy.deepcopy(payload)
                command["updated_at"] = _iso()
                if payload["status"] == "succeeded":
                    if payload["command_type"] == "ir.learn":
                        parameters = command["parameters"]
                        codes = self.ir_codes().setdefault(parameters["device"], {})
                        codes.setdefault(parameters["command"], {**copy.deepcopy(payload["result"]), "learned_at": _iso()})
                    else:
                        all_inventory.setdefault(serial, {}).pop(command["target"]["resource_id"], None)
                result = {
                    "accepted": True, "command_id": payload["command_id"],
                    "command_state": payload["status"], "duplicate": False,
                }
                self._record_sequence(protocol, message, route, result)
                try:
                    if payload["command_type"] == "ir.learn" and payload["status"] == "succeeded":
                        await self._save_ir_codes()
                        await self._save()
                    else:
                        await self._save()
                except Exception:
                    library["gateway_runtime_protocol"] = before_protocol
                    all_inventory[serial] = before_inventory
                    self.hass.data[DOMAIN]["ir_codes"] = before_codes
                    if payload["command_type"] == "ir.learn":
                        try:
                            await self._save_ir_codes()
                        except Exception:
                            pass
                    raise
            waiter = self._ir_waiters.get(payload["command_id"])
            if waiter:
                waiter[1].set()
        self._notify(serial)
        return result

    async def remove_gateway(self, serial):
        """仅在配置条目被真正移除时，删除该条目所属的数据。"""
        async with self.lock:
            self.stop(serial)
            shared = self.hass.data[DOMAIN]
            library = shared["library"]
            before_inventory = copy.deepcopy(library.get("bluetooth_devices", {}).get(serial))
            protocol = _protocol_store(library)
            before_protocol = copy.deepcopy(protocol)
            library.setdefault("bluetooth_devices", {}).pop(serial, None)
            protocol["sequences"].pop(serial, None)
            protocol["inventory_revisions"].pop(serial, None)
            for command_id in [key for key, value in protocol["commands"].items() if value.get("gateway_serial") == serial]:
                protocol["commands"].pop(command_id, None)
            try:
                await self._save()
            except Exception:
                library["gateway_runtime_protocol"] = before_protocol
                if before_inventory is not None:
                    library.setdefault("bluetooth_devices", {})[serial] = before_inventory
                raise


def _schema(route):
    return {
        vol.Required("type"): route,
        vol.Required("protocol_version"): int,
        vol.Required("schema_version"): int,
        vol.Required("gateway_serial"): str,
        vol.Required("boot_id"): str,
        vol.Required("sequence"): int,
        vol.Required("payload"): dict,
    }


async def _respond(connection, msg, validator, operation, label):
    if not connection.user.is_admin:
        connection.send_error(msg["id"], "permission_denied", "Administrator required")
        return
    try:
        validated = validator(msg)
        result = await operation(validated)
    except ValueError as error:
        connection.send_error(msg["id"], str(error), f"{label} rejected")
    except Exception:
        _LOGGER.exception("%s failed for gateway %s", label, msg.get("gateway_serial"))
        connection.send_error(msg["id"], "storage_error", f"Unable to persist {label}")
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(_schema(f"{DOMAIN}/gateway/heartbeat"))
@websocket_api.async_response
async def websocket_gateway_heartbeat(hass, connection, msg):
    await _respond(connection, msg, validate_heartbeat, coordinator(hass).heartbeat, "gateway heartbeat")


@websocket_api.websocket_command(_schema(f"{DOMAIN}/bluetooth/inventory"))
@websocket_api.async_response
async def websocket_bluetooth_inventory(hass, connection, msg):
    await _respond(connection, msg, validate_inventory, coordinator(hass).upload_inventory, "Bluetooth inventory")


@websocket_api.websocket_command(_schema(f"{DOMAIN}/gateway/get_pending_commands"))
@websocket_api.async_response
async def websocket_gateway_get_pending(hass, connection, msg):
    await _respond(connection, msg, validate_get_pending, coordinator(hass).get_pending, "pending command request")


@websocket_api.websocket_command(_schema(f"{DOMAIN}/gateway/ack_command"))
@websocket_api.async_response
async def websocket_gateway_ack(hass, connection, msg):
    await _respond(connection, msg, validate_ack, coordinator(hass).ack, "command acknowledgement")
