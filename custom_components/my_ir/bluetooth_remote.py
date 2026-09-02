"""蓝牙设备清单实体；HID 命令仅在 Android 的 TV 页面执行。"""
from homeassistant.components.remote import RemoteEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .gateway import async_remove_bluetooth_entity, coordinator, signal
from .bluetooth_data import PROTOCOL, HID_KEYS, HID_PROFILE

@callback
def setup_bluetooth_remotes(hass, entry, async_add_entities):
    serial = entry.data.get("app_serial")
    if not serial:
        return
    manager = coordinator(hass)
    entities = {}

    @callback
    def reconcile():
        """使运行中的实体与最新权威配对清单保持一致。"""
        desired = set(manager.inventory(serial))
        additions = []
        for key in desired - set(entities):
            entity = BluetoothRemote(manager, serial, key)
            entities[key] = entity
            additions.append(entity)
        if additions:
            async_add_entities(additions)
        for key in set(entities) - desired:
            entity = entities.pop(key)
            hass.async_create_task(async_remove_bluetooth_entity(hass, entity, "remote"))

    entry.async_on_unload(async_dispatcher_connect(hass, signal(serial), reconcile))
    reconcile()

class BluetoothRemote(RemoteEntity):
    """APK 管理的单个蓝牙 HID 主机的只读实体映射。

    ``is_on`` 表示 HID 协议连接状态，而不是电视电源状态。控制命令保留在 APK 的 TV 页面
    本地执行，避免 HA 延迟或断线影响按键释放报告的发送。
    """
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:bluetooth"

    def __init__(self, manager, serial, key):
        self.manager = manager
        self.serial = serial
        self.key = key
        # 保持集成可在项目的 Python 3.8 环境中测试。
        # str.removeprefix() 从 Python 3.9 才开始提供。
        stable_key = key[3:] if key.startswith("bt_") else key
        self._attr_unique_id = f"{serial}_bluetooth_{stable_key}"
        self._attr_name = "Bluetooth"
        device = self._device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": device.get("name") or "Bluetooth device",
            "model": "Bluetooth HID target",
            "via_device": (DOMAIN, serial),
        }

    @property
    def _device(self):
        return self.manager.inventory(self.serial).get(self.key, {})

    @property
    def _live(self):
        return self.manager.live(self.serial)

    @property
    def _connection(self):
        return self._live.get("devices", {}).get(self.key, {})

    @property
    def available(self):
        return (self._live.get("adapter_state") == "on"
                and self._live.get("permission_state") == "granted"
                and "bluetooth_hid" in self._live.get("capabilities", set())
                and "bluetooth_inventory" in self._live.get("capabilities", set())
                and self._device.get("paired", False)
                and self._device.get("bluetooth_type") != "le"
                and self._connection.get("hid_support") != "unsupported")

    @property
    def is_on(self):
        return self.available and self._connection.get("connection_state") == "connected"

    @property
    def extra_state_attributes(self):
        device = self._device
        connection = self._connection
        return {
            "control_protocol": PROTOCOL, "gateway_serial": self.serial,
            "bluetooth_device_id": self.key,
            "bluetooth_address": device.get("bluetooth_address"),
            "bluetooth_name": device.get("name"),
            "bluetooth_type": device.get("bluetooth_type"),
            "paired": device.get("paired", False),
            "adapter_state": self._live.get("adapter_state", "unknown"),
            "connection_state": connection.get("connection_state", "disconnected"),
            "hid_support": ("unsupported" if device.get("bluetooth_type") == "le"
                            else connection.get("hid_support", "unknown")),
            "hid_profile": HID_PROFILE, "supported_hid_keys": list(HID_KEYS),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, signal(self.serial), self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    async def async_send_command(self, command, **kwargs):
        raise HomeAssistantError("Bluetooth HID control is currently available only in the APK TV detail page")

    async def async_turn_on(self, **kwargs):
        raise HomeAssistantError("This entity reports HID connectivity, not TV power")

    async def async_turn_off(self, **kwargs):
        raise HomeAssistantError("Use the APK Bluetooth settings to manage the adapter")
