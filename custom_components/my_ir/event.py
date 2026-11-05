"""网关重力感应事件实体：拿起、移动、停止。"""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gateway import (
    CAPABILITY_MOTION_EVENT,
    coordinator,
    gateway_device_info,
    signal,
)

MOTION_EVENT_TYPES = ["picked_up", "placed_down", "motion_detected"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """按网关能力动态创建重力感应事件实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_MOTION_EVENT,
        "motion",
        async_add_entities,
        lambda: [GatewayMotionEvent(manager, serial)],
    )


class GatewayMotionEvent(EventEntity):
    """网关上报的拿起、移动、停止事件。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "motion"
    _attr_device_class = EventDeviceClass.MOTION
    _attr_event_types = MOTION_EVENT_TYPES

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        # 创建前已经产生的事件不重放，只响应之后的新事件。
        self._last_counter = manager.motion_status(serial).get("counter")
        self._attr_unique_id = f"{serial}_motion"
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(self._serial, CAPABILITY_MOTION_EVENT)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """网关状态变化时触发新事件，同一计数不重复触发。"""
        motion = self._manager.motion_status(self._serial)
        counter = motion.get("counter")
        event_type = motion.get("event_type")
        if counter is not None and counter != self._last_counter:
            self._last_counter = counter
            if event_type:
                self._trigger_event(event_type)
                self.async_write_ha_state()
                return
        self.async_write_ha_state()
