"""Gateway button entities."""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create gateway action buttons."""
    parent_serial = entry.data.get("app_serial")
    if not parent_serial:
        return

    async_add_entities([GatewayRefreshButton(hass, parent_serial)], True)


class GatewayRefreshButton(ButtonEntity):
    """Button that asks the Android gateway to refresh its HA data."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, hass: HomeAssistant, serial: str) -> None:
        self.hass = hass
        self._serial = serial
        self._attr_unique_id = f"{serial}_refresh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Smart Remote SN:{serial}",
            "manufacturer": "Sanytron",
            "model": "IR Gateway",
        }

    async def async_press(self) -> None:
        """Request an Android-side refresh."""
        self.hass.bus.async_fire(
            f"{DOMAIN}/refresh_request",
            {
                "serial_number": self._serial,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "button",
            },
        )
        _LOGGER.info("Gateway %s refresh requested from HA button", self._serial)
