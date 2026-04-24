from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    library = hass.data[DOMAIN]["library"]
    entities = []
    for serial, device_data in library.get("devices", {}).items():
        entities.append(MyIRRemote(hass, serial, device_data))
    async_add_entities(entities, True)  # 更新已有实体


class MyIRRemote(RemoteEntity):
    """IR 遥控器实体"""
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, serial: str, device_data: dict):
        self._serial = serial
        self._device_data = device_data
        self.hass = hass

        # 关键修复：不要手动设置 entity_id，让 HA 自动生成
        self._attr_unique_id = serial
        self._attr_name = device_data.get("name", "IR 遥控器")

        # 推荐生成干净的 entity_id（只做建议，HA 会自动处理）
        suggested_key = device_data.get("device_key", serial.lower().replace(" ", "_"))
        # 清理非法字符
        clean_key = "".join(c for c in suggested_key.lower() if c.isalnum() or c == "_")
        self.entity_id = f"remote.{device_data.get('device_key')}"

        # 关联到设备（用于“移除设备”按钮）
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._serial)},
            "name": self._attr_name,
            "manufacturer": "Sanytron",
            "model": "Infrared Remote",
            # 【关键】让 HA 知道这个遥控器是插在哪个 App 网关上的
            "via_device": (DOMAIN, device_data.get("parent_app_serial"))
        }
        
    @property
    def extra_state_attributes(self):
        """将关键信息暴露给前端，红外实体专注控制"""
        buttons = self._device_data.get("buttons", {})
        return {
            "supported_keys": list(buttons.keys()), 
            "source": self._device_data.get("source", "cloud"),
            "serial_number": self._serial, 
            "parent_app_serial": self._device_data.get("parent_app_serial")
        }

    # （可选）支持 HA 原生的 remote.send_command 调用
    async def async_send_command(self, command: list[str], **kwargs) -> None:
        """支持原生的 remote.send_command 服务"""
        buttons = self._device_data.get("buttons", {})
        for cmd in command:
            actual_ir_code = buttons.get(cmd, cmd)
            self.hass.bus.async_fire(f"{DOMAIN}/control_command", {
                "serial_number": self._serial,
                "button": actual_ir_code,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            })