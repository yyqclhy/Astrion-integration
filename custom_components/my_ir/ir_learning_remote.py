"""每台配对HA100提供一个使用HA标准学习及删除动作的遥控实体。"""
from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .gateway import coordinator, signal
from .ir_learning_data import validate_names, validate_raw_code


class IrLearningRemote(RemoteEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "IR Learning"
    _attr_icon = "mdi:remote"
    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND

    def __init__(self, hass, serial):
        self.manager = coordinator(hass)
        self.serial = serial
        self._attr_unique_id = f"{serial}_ir_learning"
        self._attr_device_info = {"identifiers": {(DOMAIN, serial)}}

    @property
    def is_on(self):
        # 表示网关具备学习能力，不代表芯片当前供电。
        return self.manager.has_capability(self.serial, "ir_learning_uart")

    @property
    def available(self):
        # APK离线时仍可删除及查询已保存的码。
        return self.serial in self.manager.active

    @property
    def extra_state_attributes(self):
        codes = self.manager.ir_codes(self.serial)
        return {
            "control_protocol": "ir_learning",
            "parent_app_serial": self.serial,
            "gateway_serial": self.serial,
            "supported_keys": sorted({key for device in codes.values() for key in device}),
            "learned_devices": sorted(codes),
            "learning": self.manager.command_active(self.serial, "ir_learning"),
            "learning_mode": "uart",
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, signal(self.serial), self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    async def async_learn_command(self, **kwargs):
        try:
            device, commands = validate_names(kwargs.get("device"), kwargs.get("command"))
            timeout = kwargs.get("timeout", 30)
            if type(timeout) is not int or not 1 <= timeout <= 120:
                raise ValueError("Learning timeout must be between 1 and 120 seconds")
            if kwargs.get("command_type", "ir") != "ir" or kwargs.get("alternative", False):
                raise ValueError("Only IR learning without alternative codes is supported")
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        for command in commands:
            await self.manager.learn_ir(self.serial, device, command, timeout)

    async def async_delete_command(self, **kwargs):
        try:
            device, commands = validate_names(kwargs.get("device"), kwargs.get("command"))
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        await self.manager.delete_ir(self.serial, device, commands)

    async def async_send_command(self, command, **kwargs):
        # TV编辑器测试沿用原广播链路，此处支持HA标准发送动作。
        if isinstance(command, str):
            command = [command]
        if not command:
            raise HomeAssistantError("Specify a command")
        if kwargs.get("num_repeats", 1) != 1 or kwargs.get("hold_secs", 0):
            raise HomeAssistantError("IR learning remote currently supports single sends only")
        codes = self.manager.ir_codes(self.serial).get(kwargs.get("device"), {})
        values = []
        for key in command:
            code = codes.get(key, {}).get("code") if kwargs.get("device") else key
            try:
                validate_raw_code(code)
            except ValueError as error:
                raise HomeAssistantError("Learned IR command not found or invalid") from error
            values.append(code)
        for code in values:
            self.hass.bus.async_fire(f"{DOMAIN}/control_command", {
                "serial_number": self.serial, "button": code,
            })

    async def async_turn_on(self, **kwargs):
        raise HomeAssistantError("Use remote.learn_command; chip power is managed by the APK")

    async def async_turn_off(self, **kwargs):
        raise HomeAssistantError("Chip power is managed by the APK, not remote.turn_off")
