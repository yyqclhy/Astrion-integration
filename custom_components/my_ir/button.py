"""网关按钮实体。"""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .gateway import (
    CAPABILITY_DEVICE_CONTROL,
    DEVICE_COMMAND_SCREEN_OFF,
    DEVICE_COMMAND_SCREEN_ON,
    async_reconcile_bluetooth_registry,
    coordinator,
    gateway_device_info,
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
    # 新版本不再创建蓝牙取消配对按钮，加载时清理旧注册表记录。
    await async_reconcile_bluetooth_registry(
        hass, parent_serial, manager.inventory(parent_serial)
    )
    async_add_entities([GatewayRefreshButton(manager, parent_serial)], True)
    manager.register_capability_entity_adder(
        parent_serial,
        CAPABILITY_DEVICE_CONTROL,
        "screen_control",
        async_add_entities,
        lambda: [
            GatewayScreenButton(manager, parent_serial, "screen_wake", DEVICE_COMMAND_SCREEN_ON, "mdi:monitor"),
            GatewayScreenButton(manager, parent_serial, "screen_sleep", DEVICE_COMMAND_SCREEN_OFF, "mdi:monitor-off"),
        ],
    )

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


class GatewayScreenButton(ButtonEntity):
    """通过短有效期控制命令触发网关屏幕唤醒或息屏。"""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager, serial: str, key: str, command_type: str, icon: str) -> None:
        self._manager = manager
        self._serial = serial
        self._command_type = command_type
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(self._serial, CAPABILITY_DEVICE_CONTROL)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )

    async def async_press(self) -> None:
        await self._manager.send_device_control(self._serial, self._command_type, {})
