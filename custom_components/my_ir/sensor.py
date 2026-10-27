"""网关设备状态实体：电池电量。"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    """按网关能力动态创建电量实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_DEVICE_STATUS,
        "battery",
        async_add_entities,
        lambda: [GatewayBatterySensor(manager, serial)],
    )


class GatewayBatterySensor(SensorEntity):
    """网关电池电量百分比。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        self._attr_unique_id = f"{serial}_battery"
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(
            self._serial, CAPABILITY_DEVICE_STATUS
        ) and bool(self._manager.status(self._serial))

    @property
    def native_value(self) -> int | None:
        return self._manager.status(self._serial).get("battery_level")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )
