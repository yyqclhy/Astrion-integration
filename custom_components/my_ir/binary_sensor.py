"""网关设备状态实体：充电状态与屏幕状态。"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gateway import (
    CAPABILITY_DEVICE_STATUS,
    coordinator,
    gateway_device_info,
    signal,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """按网关能力动态创建充电与屏幕状态实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_DEVICE_STATUS,
        "device_state",
        async_add_entities,
        lambda: [
            GatewayChargingBinarySensor(manager, serial),
            GatewayScreenBinarySensor(manager, serial),
        ],
    )


class _GatewayStatusBinarySensor(BinarySensorEntity):
    """网关状态二值实体的公共状态订阅。"""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(
            self._serial, CAPABILITY_DEVICE_STATUS
        ) and bool(self._manager.status(self._serial))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )


class GatewayChargingBinarySensor(_GatewayStatusBinarySensor):
    """设备当前是否正在充电，与是否接入电源区分。"""

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, manager, serial: str) -> None:
        super().__init__(manager, serial)
        self._attr_unique_id = f"{serial}_charging"

    @property
    def is_on(self) -> bool | None:
        return self._manager.status(self._serial).get("charging")


class GatewayScreenBinarySensor(_GatewayStatusBinarySensor):
    """设备屏幕当前是否点亮。"""

    _attr_translation_key = "screen_on"
    # HA 的 BinarySensorDeviceClass 没有 screen 成员，这里只用图标区分。
    _attr_icon = "mdi:monitor"

    def __init__(self, manager, serial: str) -> None:
        super().__init__(manager, serial)
        self._attr_unique_id = f"{serial}_screen_on"

    @property
    def is_on(self) -> bool | None:
        return self._manager.status(self._serial).get("screen_on")
