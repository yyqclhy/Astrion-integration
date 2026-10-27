"""网关屏幕亮度控制实体。"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gateway import (
    CAPABILITY_DEVICE_CONTROL,
    DEVICE_COMMAND_BRIGHTNESS,
    coordinator,
    gateway_device_info,
    signal,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """按网关能力动态创建亮度实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_DEVICE_CONTROL,
        "screen_brightness",
        async_add_entities,
        lambda: [GatewayBrightnessNumber(manager, serial)],
    )


class GatewayBrightnessNumber(NumberEntity):
    """HA 侧按 0～100 显示亮度，下发时换算为设备原始 0～255。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "screen_brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        self._attr_unique_id = f"{serial}_screen_brightness"
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(
            self._serial, CAPABILITY_DEVICE_CONTROL
        ) and bool(self._manager.status(self._serial))

    @property
    def native_value(self) -> int | None:
        raw = self._manager.status(self._serial).get("brightness")
        if not isinstance(raw, int):
            return None
        return round(raw * 100 / 255)

    async def async_set_native_value(self, value: float) -> None:
        """把百分比换算成设备原始亮度后提交命令，实际值由状态上报回传。"""
        raw = max(0, min(255, round(value * 255 / 100)))
        await self._manager.send_device_control(
            self._serial, DEVICE_COMMAND_BRIGHTNESS, {"brightness": raw}
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )
