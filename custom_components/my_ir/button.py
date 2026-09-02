"""网关按钮实体。"""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .gateway import (
    async_reconcile_bluetooth_registry,
    async_remove_bluetooth_entity,
    coordinator,
    signal,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """创建网关操作按钮。"""
    parent_serial = entry.data.get("app_serial")
    if not parent_serial:
        return

    manager = coordinator(hass)
    async_add_entities([GatewayRefreshButton(manager, parent_serial)], True)
    _setup_unpair_buttons(hass, entry, async_add_entities, manager, parent_serial)


@callback
def _setup_unpair_buttons(hass, entry, async_add_entities, manager, serial):
    """为每个已配对蓝牙目标动态维护一个取消配对按钮。"""
    entities = {}

    @callback
    def reconcile():
        desired = set(manager.inventory(serial))
        additions = []
        for resource_id in desired - set(entities):
            entity = BluetoothUnpairButton(manager, serial, resource_id)
            entities[resource_id] = entity
            additions.append(entity)
        if additions:
            async_add_entities(additions)
        for resource_id in set(entities) - desired:
            entity = entities.pop(resource_id)
            hass.async_create_task(async_remove_bluetooth_entity(hass, entity, "button"))

        # 同时清理旧版本未实际删除设备注册表记录而留下的残余条目。
        # 此清理操作可安全地重复执行。
        hass.async_create_task(
            async_reconcile_bluetooth_registry(hass, serial, manager.inventory(serial))
        )

    entry.async_on_unload(async_dispatcher_connect(hass, signal(serial), reconcile))
    reconcile()

class GatewayRefreshButton(ButtonEntity):
    """请求 Android 网关刷新其 HA 数据的按钮。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        self._attr_unique_id = f"{serial}_refresh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Smart Remote SN:{serial}",
            "manufacturer": "Sanytron",
            "model": "IR Gateway",
        }

    @property
    def available(self) -> bool:
        return self._manager.has_capability(self._serial, "device_refresh")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )

    async def async_press(self) -> None:
        """请求 Android 端刷新数据。"""
        if not self.available:
            raise HomeAssistantError("Gateway is offline or does not support refresh")
        self.hass.bus.async_fire(
            f"{DOMAIN}/refresh_request",
            {
                "serial_number": self._serial,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "button",
            },
        )
        _LOGGER.info("Gateway %s refresh requested from HA button", self._serial)


class BluetoothUnpairButton(ButtonEntity):
    """创建持久化取消配对命令；只有收到成功 ACK 后才移除实体。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # 实体名称由 strings.json / translations 按 HA 当前语言提供，禁止在代码中硬编码。
    _attr_translation_key = "unpair"
    _attr_icon = "mdi:bluetooth-off"

    def __init__(self, manager, serial: str, resource_id: str) -> None:
        self._manager = manager
        self._serial = serial
        self._resource_id = resource_id
        stable_key = resource_id[3:] if resource_id.startswith("bt_") else resource_id
        self._attr_unique_id = f"{serial}_bluetooth_{stable_key}_unpair"
        device = manager.inventory(serial).get(resource_id, {})
        remote_unique_id = f"{serial}_bluetooth_{stable_key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, remote_unique_id)},
            "name": device.get("name") or "Bluetooth device",
            "model": "Bluetooth HID target",
            "via_device": (DOMAIN, serial),
        }

    @property
    def available(self) -> bool:
        return self._manager.can_unpair(self._serial, self._resource_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )

    async def async_press(self) -> None:
        if not self.available:
            raise HomeAssistantError("Bluetooth unpair is currently unavailable")
        await self._manager.create_unpair(self._serial, self._resource_id)
