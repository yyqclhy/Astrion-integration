"""处理已认证 APK 的设备清单上报，并按网关隔离蓝牙运行状态。"""
import asyncio
from datetime import timedelta
import logging
from time import monotonic

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .bluetooth_data import validate_upload, merge_inventory, device_id

ONLINE_TIMEOUT = 180
EXPIRY_INTERVAL = 30
_LOGGER = logging.getLogger(__name__)

def signal(serial):
    return f"{DOMAIN}_gateway_{serial}"

def coordinator(hass):
    data = hass.data.setdefault(DOMAIN, {})
    if "bluetooth" not in data:
        data["bluetooth"] = BluetoothCoordinator(hass)
    return data["bluetooth"]

class BluetoothCoordinator:
    """管理需持久化的蓝牙清单事务，以及不持久化的实时状态。

    所有 Astrion 配置条目共用一个协调器。``active`` 限定允许 APK 上报的网关范围；
    ``runtime`` 保存仅在心跳有效期内可信的适配器与连接数据，
    Home Assistant 重启后绝不能从旧数据恢复这些实时状态。
    """

    def __init__(self, hass):
        self.hass = hass
        self.active = set()
        self.runtime = {}
        self.lock = asyncio.Lock()
        self._unsub = None

    def start(self, serial):
        self.active.add(serial)
        if self._unsub is None:
            self._unsub = async_track_time_interval(
                self.hass, self._expire, timedelta(seconds=EXPIRY_INTERVAL)
            )

    def _notify(self, serial):
        """通知实体更新，避免界面监听器失败导致 APK 重试上报。"""
        try:
            async_dispatcher_send(self.hass, signal(serial))
        except Exception:  # 实体监听器异常不能导致已经保存的快照回滚。
            _LOGGER.exception("Bluetooth entity update failed for gateway %s", serial)

    def stop(self, serial):
        self.active.discard(serial)
        self.runtime.pop(serial, None)
        if not self.active and self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _expire(self, now):
        for serial in tuple(self.active):
            state = self.runtime.get(serial)
            if state and monotonic() - state["seen"] > ONLINE_TIMEOUT and not state.get("expired"):
                state["expired"] = True
                self._notify(serial)

    def inventory(self, serial):
        return self.hass.data[DOMAIN].get("library", {}).get("bluetooth_devices", {}).get(serial, {})

    def live(self, serial):
        state = self.runtime.get(serial, {})
        return state if monotonic() - state.get("seen", 0) <= ONLINE_TIMEOUT else {}

    async def remove_gateway(self, serial):
        """仅在移除配置条目时删除本网关清单，重载时不删除。"""
        async with self.lock:
            self.stop(serial)
            shared = self.hass.data[DOMAIN]
            inventory = shared.get("library", {}).get("bluetooth_devices", {})
            if serial not in inventory:
                return
            previous = inventory.pop(serial)
            try:
                await shared["store"].async_save(shared["library"])
            except Exception:
                inventory[serial] = previous
                raise

    async def upload(self, data):
        serial = data["serial_number"]
        async with self.lock:
            if serial not in self.active:
                raise ValueError("unknown_gateway")
            shared = self.hass.data[DOMAIN]
            inventory = shared["library"].setdefault("bluetooth_devices", {})
            existed = serial in inventory
            before = inventory.get(serial, {})
            after = merge_inventory(before, data)
            if after != before:
                inventory[serial] = after
                try:
                    await shared["store"].async_save(shared["library"])
                except Exception:
                    # 精确恢复原字典结构，包括首次上报前该网关条目不存在的情况。
                    if existed:
                        inventory[serial] = before
                    else:
                        inventory.pop(serial, None)
                    raise
            # 此处仅保留运行时状态，防止 HA 重启后误恢复旧的连接状态。
            devices = {}
            if data["inventory_complete"]:
                devices = {device_id(d["bluetooth_address"]): d for d in data["devices"]}
            elif data["adapter_state"] == "on" and data["permission_state"] == "granted":
                devices = self.live(serial).get("devices", {})
            self.runtime[serial] = {
                "seen": monotonic(), "adapter_state": data["adapter_state"],
                "permission_state": data["permission_state"], "devices": devices,
                "capabilities": {"bluetooth_hid", "bluetooth_inventory", "bluetooth_unpair"},
            }
            self._notify(serial)
            return sum(1 for d in after.values() if d.get("paired"))

@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/submit_bluetooth_devices",
    vol.Required("schema_version"): int,
    vol.Required("serial_number"): str,
    vol.Required("adapter_state"): str,
    vol.Required("permission_state"): str,
    vol.Required("inventory_complete"): bool,
    vol.Optional("devices"): list,
})
@websocket_api.async_response
async def websocket_submit_bluetooth_devices(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg["id"], "permission_denied", "Administrator required for inventory uploads")
        return
    try:
        data = validate_upload(msg)
        count = await coordinator(hass).upload(data)
    except ValueError as error:
        connection.send_error(msg["id"], str(error), "Bluetooth inventory rejected")
        return
    except Exception:
        _LOGGER.exception("Unable to persist Bluetooth inventory for gateway %s", msg.get("serial_number"))
        connection.send_error(msg["id"], "storage_error", "Unable to save Bluetooth inventory")
        return
    connection.send_result(msg["id"], {"accepted": True, "device_count": count})
