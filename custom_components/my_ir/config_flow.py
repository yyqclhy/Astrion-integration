from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
import voluptuous as vol
from .const import DOMAIN
import logging
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

CLOUD_JSON_URL = "https://raw.githubusercontent.com/yyqclhy/ha-tv-remote-data/main/test/ir-data.json"

class MyIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """配置流程 (首次添加集成网关时触发)"""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """启用选项流，并在集成卡片上显示‘配置’按钮"""
        return MyIROptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """步骤：添加集成网关"""
        
        # 【重要】这里绝对没有 single_instance_allowed 的判断了！
        
        if user_input is not None:
            # 只有点击提交后，才会发出单次广播
            self.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
                "code": "DISCOVER_ALL",
                "mode": "discover_all",
                "timestamp": datetime.utcnow().isoformat(),
                "source": "config_flow"
            })
            _LOGGER.info("已通过配置向导广播单次配对请求")

            # 创一个空条目，等 App 连上来
            return self.async_create_entry(
                title="IR 遥控网关 (等待连接)",
                data={}
            )

        # 界面仅显示提示，不需要任何输入框
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "desc": "点击【提交】以添加一个新的 App 遥控网关。\n\nHA 将向局域网广播单次配对指令，请确保您的 App 已打开并准备好接收。"
            }
        )

# ====================== 选项流 (点击“配置”按钮后触发) ======================
class MyIROptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._cloud_data = None
        self._selected_type = None

    async def _fetch_cloud_data(self):
        """异步拉取云端数据"""
        if self._cloud_data is None:
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(CLOUD_JSON_URL, timeout=10) as response:
                    if response.status == 200:
                        self._cloud_data = await response.json(content_type=None)
                    else:
                        _LOGGER.error("获取云端码库失败: %s", response.status)
                        self._cloud_data = {"brands": []}
            except Exception as e:
                _LOGGER.error("获取云端码库异常: %s", e)
                self._cloud_data = {"brands": []}
        return self._cloud_data

    async def async_step_init(self, user_input=None) -> FlowResult:
        """点击配置按钮后触发"""
        # 【关键拦截】检查该条目是否已经配对成功
        if not self.config_entry.data.get("app_serial"):
            # 如果还没 app_serial，直接弹窗报错，拒绝进入下一步
            return self.async_abort(reason="not_paired_yet")
            
        return await self.async_step_cloud_type()

    async def async_step_cloud_type(self, user_input=None) -> FlowResult:
        """云端第一步：选择设备类型（电视、空调等）"""
        cloud_data = await self._fetch_cloud_data()
        brands = cloud_data.get("brands", [])

        if not brands:
            return self.async_abort(reason="cloud_fetch_failed")

        type_map = {b["device_type"]: b["device_type_name"] for b in brands}

        if user_input is not None:
            self._selected_type = user_input["device_type"]
            return await self.async_step_cloud_device()

        return self.async_show_form(
            step_id="cloud_type",
            data_schema=vol.Schema({
                vol.Required("device_type"): vol.In(type_map)
            })
        )

    async def async_step_cloud_device(self, user_input=None) -> FlowResult:
        """云端第二步：选择具体设备型号"""
        cloud_data = await self._fetch_cloud_data()
        devices = []
        for b in cloud_data.get("brands", []):
            if b["device_type"] == self._selected_type:
                devices = b.get("devices", [])
                break

        device_map = {d["id"]: d["name"] for d in devices}

        if user_input is not None:
            selected_id = user_input["device_id"]
            selected_device = next((d for d in devices if d["id"] == selected_id), None)
            if selected_device:
                return await self.async_save_cloud_device(selected_device)

        return self.async_show_form(
            step_id="cloud_device",
            data_schema=vol.Schema({
                vol.Required("device_id"): vol.In(device_map)
            })
        )

    async def async_save_cloud_device(self, device_data: dict) -> FlowResult:
        """最后一步：保存云端子设备数据并触发异步重载"""
        library = self.hass.data[DOMAIN].setdefault("library", {"devices": {}})
        
        # 获取父级 App 的串号
        parent_app_serial = self.config_entry.data.get("app_serial", "unknown")
        
        # 【关键修复】将父级串号融入红外设备的 ID，彻底解决不同 App 下添加同一型号的冲突！
        serial = f"IR_{parent_app_serial}_{device_data['id']}"
        
        buttons = {key_info["name"]: key_info["ir"] for key_info in device_data.get("keys", [])}

        device_info = {
            "serial_number": serial,
            "device_key": f"sanytron_{device_data['id']}_{parent_app_serial[-4:]}", # 让实体 ID 带上 Sanytron 和 父级尾号
            "name": f"Sanytron {device_data['name']}", # 强制带上 Sanytron 标识
            "buttons": buttons,
            "source": "cloud",
            "parent_app_serial": parent_app_serial 
        }

        library["devices"][serial] = device_info
        await self.hass.data[DOMAIN]["store"].async_save(library)
        
        new_data = dict(self.config_entry.data)
        new_data.setdefault("devices", {})
        new_data["devices"][serial] = device_info
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )

        return self.async_create_entry(title=f"已挂载: {device_data['name']}", data={})