from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
import voluptuous as vol
from .const import DOMAIN
from homeassistant.helpers import selector
import logging
import json
import asyncio
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://astrion.lifex360.com/api/v1"
# 按键控制，喇叭播放，电量，屏幕唤醒集成到HA中，在

class MyIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """配置流程 (首次添加集成网关时触发)"""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """启用选项流，并在集成卡片上显示‘配置’按钮"""
        return MyIROptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """点击集成名称即发送配对请求，无需中间表单"""
        
        # 【关键】确保 WebSocket 处理器已注册（async_setup 可能未被调用）
        from homeassistant.components import websocket_api
        from . import websocket_submit_pair_data, websocket_get_device_codes, websocket_get_harmony_config
        websocket_api.async_register_command(self.hass, websocket_submit_pair_data)
        websocket_api.async_register_command(self.hass, websocket_get_device_codes)
        websocket_api.async_register_command(self.hass, websocket_get_harmony_config)
        _LOGGER.info("【config_flow】WebSocket 处理器已在配置流程中注册")
        
        # 开始新配对前，清理上次残留的发现列表
        self.hass.data.setdefault(DOMAIN, {}).pop("discovered_gateways", None)
        
        # 直接发出配对广播
        self.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
            "code": "DISCOVER_ALL",
            "mode": "discover_all",
            "timestamp": datetime.utcnow().isoformat(),
            "source": "config_flow"
        })
        _LOGGER.info("已通过配置向导广播配对请求，等待 5 秒…")
        
        # 等待 5 秒让 App 响应
        await asyncio.sleep(5)
        
        discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})
        _LOGGER.info("5秒后发现列表有 %d 个网关: %s", len(discovered), list(discovered.keys()))
        
        # 进入发现步骤
        return await self.async_step_discover()

    async def async_step_discover(self, user_input: dict | None = None) -> FlowResult:
        """显示已发现的网关列表，或重试搜索"""
        discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})

        if user_input is not None:
            selected_serial = user_input.get("gateway")
            if selected_serial and selected_serial in discovered:
                gw_data = discovered[selected_serial]
                model = gw_data.get("model", "IR Gateway")
                # 创建条目，填入 App 信息
                return self.async_create_entry(
                    title=f"Smart Remote:{model} SN:{selected_serial}",
                    data={
                        "app_serial": selected_serial,
                        "app_model": model
                    }
                )
            # 用户点了重试按钮
            if user_input.get("retry"):
                self.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
                    "code": "DISCOVER_ALL",
                    "mode": "discover_all",
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "config_flow"
                })
                _LOGGER.info("用户要求重新搜索网关，等待 5 秒…")
                await asyncio.sleep(5)
                # 重试后重新读取发现列表
                discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})

        _LOGGER.info("【discover最终检查】discovered_gateways=%s, len=%d", dict(discovered), len(discovered))
        
        # 检查是否有发现的网关
        if discovered:
            _LOGGER.info("【discover】有发现！显示选择列表，共 %d 个", len(discovered))
            options = [
                {"value": s, "label": f"Smart Remote:{d.get('model','IR Gateway')} SN:{s}"}
                for s, d in discovered.items()
            ]
            return self.async_show_form(
                step_id="discover",
                data_schema=vol.Schema({
                    vol.Required("gateway"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode="list")
                    )
                }),
                description_placeholders={
                    "count": str(len(discovered))
                }
            )
        else:
            _LOGGER.info("【discover】无发现，显示重试界面")
            # 无发现，显示重试界面
            return self.async_show_form(
                step_id="discover_retry",
                data_schema=vol.Schema({
                    vol.Optional("retry", default=False): selector.BooleanSelector(
                        selector.BooleanSelectorConfig()
                    )
                })
            )


# ====================== 选项流 (点击“配置”按钮后触发) ======================
class MyIROptionsFlowHandler(config_entries.OptionsFlow):
    """API驱动的新设备添加流程（不需要头认证）"""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        # 步骤1: 库
        self._depot_id = None
        self._depot_name = None
        self._depot_id_map = {}
        # 步骤2: 设备分类
        self._category_id = None
        self._category_name = None
        self._cat_id_map = {}
        # 步骤3: 品牌
        self._brand_id = None
        self._brand_name = None
        self._brand_id_map = {}
        # 步骤4: 驱动列表（分页收集）
        self._all_drives = []
        self._drive_label_map = {}

    # ------------------------------------------------------------------
    #  API 请求工具（无认证头）
    # ------------------------------------------------------------------

    async def _api_get(self, path: str, params: dict = None) -> dict | list:
        """向API发送无认证的GET请求"""
        session = async_get_clientsession(self.hass)
        url = f"{API_BASE_URL}{path}"
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                _LOGGER.error("API请求失败 [%s] %s: %s", resp.status, url, await resp.text()[:200])
        except Exception as e:
            _LOGGER.error("API请求异常 %s: %s", url, e)
        return {}

    @staticmethod
    def _extract_list(resp, default_key="rows"):
        """从API响应中提取列表数据，兼容多种返回格式"""
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            # 尝试常见的包裹key
            for key in ("data", default_key, "list", "records", "result", "items"):
                val = resp.get(key)
                if isinstance(val, list):
                    return val
            # 如果code/msg包装，递归找第一个list值
            for v in resp.values():
                if isinstance(v, list):
                    return v
        return []

    # ------------------------------------------------------------------
    #  入口
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None) -> FlowResult:
        """点击配置按钮后触发"""
        if not self.config_entry.data.get("app_serial"):
            return self.async_abort(reason="not_paired_yet")
        return await self.async_step_depot()

    # ------------------------------------------------------------------
    #  步骤1: 选择库
    # ------------------------------------------------------------------

    async def async_step_depot(self, user_input=None) -> FlowResult:
        """第一步：从API获取库列表，用户选择"""
        if user_input is not None:
            selected = user_input["depot_id"]
            if selected not in self._depot_id_map:
                return await self.async_step_depot()
            self._depot_id = self._depot_id_map[selected]
            self._depot_name = selected
            _LOGGER.info("已选择库: %s (%s)", self._depot_name, self._depot_id)
            return await self.async_step_category()

        data = await self._api_get("/rc/app/depot/list")
        depots = self._extract_list(data)

        if not depots:
            return self.async_abort(reason="cloud_fetch_failed")

        self._depot_id_map = {}
        self._depot_opts = []
        for d in depots:
            did = str(d.get("depotId") or d.get("id"))
            dname = d.get("depotName") or d.get("name") or "未知库"
            if did:
                self._depot_opts.append({"value": dname, "label": dname})
                self._depot_id_map[dname] = did

        return self.async_show_form(
            step_id="depot",
            data_schema=vol.Schema({
                vol.Required("depot_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._depot_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={
                "desc": "请选择要添加设备的红外库"
            }
        )

    # ------------------------------------------------------------------
    #  步骤2: 选择设备分类
    # ------------------------------------------------------------------

    async def async_step_category(self, user_input=None) -> FlowResult:
        """第二步：从API获取设备分类列表，用户选择"""
        if user_input is not None:
            selected = user_input["category_id"]
            if selected not in self._cat_id_map:
                return await self.async_step_category()
            self._category_id = self._cat_id_map[selected]
            self._category_name = selected
            _LOGGER.info("已选择分类: %s (%s)", self._category_name, self._category_id)
            return await self.async_step_brand()

        data = await self._api_get("/rc/app/category/list")
        categories = self._extract_list(data)

        if not categories:
            return self.async_abort(reason="cloud_fetch_failed")

        self._cat_id_map = {}
        self._cat_opts = []
        for c in categories:
            cid = str(c.get("categoryId") or c.get("id") or c.get("category_id"))
            cname = c.get("categoryName") or c.get("name") or "未知分类"
            if cid:
                self._cat_opts.append({"value": cname, "label": cname})
                self._cat_id_map[cname] = cid

        return self.async_show_form(
            step_id="category",
            data_schema=vol.Schema({
                vol.Required("category_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._cat_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={
                "desc": "请选择设备类型（如电视、空调等）"
            }
        )

    # ------------------------------------------------------------------
    #  步骤3: 选择品牌
    # ------------------------------------------------------------------

    async def async_step_brand(self, user_input=None) -> FlowResult:
        """第三步：从API获取品牌列表，用户选择"""
        if user_input is not None:
            selected = user_input["brand_id"]
            if selected not in self._brand_id_map:
                return await self.async_step_brand()
            self._brand_id = self._brand_id_map[selected]
            self._brand_name = selected
            _LOGGER.info("已选择品牌: %s (%s)", self._brand_name, self._brand_id)
            return await self.async_step_drive_list()

        data = await self._api_get("/rc/app/brand/all")
        brands = self._extract_list(data)

        if not brands:
            return self.async_abort(reason="cloud_fetch_failed")

        self._brand_id_map = {}
        self._brand_opts = []
        for b in brands:
            bid = str(b.get("brandId") or b.get("id"))
            bname = b.get("brandName") or b.get("name") or "未知品牌"
            if bid:
                self._brand_opts.append({"value": bname, "label": bname})
                self._brand_id_map[bname] = bid

        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({
                vol.Required("brand_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._brand_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={
                "desc": "请选择设备品牌"
            }
        )

    # ------------------------------------------------------------------
    #  步骤4: 分页查询所有驱动 → 用户选择
    # ------------------------------------------------------------------

    async def async_step_drive_list(self, user_input=None) -> FlowResult:
        """第四步：分页获取驱动列表，用户选择一条"""
        if user_input is not None:
            selected = user_input["drive_index"]
            if selected not in self._drive_label_map:
                return await self.async_step_drive_list()
            return await self._save_drive(self._drive_label_map[selected])

        # 首次进入：分页收集所有驱动，查到最后一页为止
        self._all_drives = []
        page_size = 10
        page_num = 1

        while True:
            resp = await self._api_get("/rc/app/drive/list", {
                "source": "0",
                "categoryId": self._category_id,
                "depotId": self._depot_id,
                "brandId": self._brand_id,
                "pageSize": str(page_size),
                "pageNum": str(page_num),
            })

            rows = resp.get("rows", [])
            if not rows:
                break

            self._all_drives.extend(rows)
            _LOGGER.info("驱动列表第%d页: 获取到%d条", page_num, len(rows))

            # 如果这一页返回少于 pageSize 条，说明已到最后一页，停止
            if len(rows) < page_size:
                break

            page_num += 1

        if not self._all_drives:
            _LOGGER.warning("未找到任何驱动: category=%s, depot=%s, brand=%s",
                            self._category_id, self._depot_id, self._brand_id)
            return self.async_abort(reason="no_drives_found")

        # 可搜索的下拉框（用 label 文本作为 value，combo box 才能显示名称）
        self._drive_opts = []
        self._drive_label_map = {}
        for i, d in enumerate(self._all_drives):
            brand_name = d.get("brand", {}).get("brandName", "")
            model = d.get("modelName", "未知型号")
            official = "官方" if d.get("isOfficial") == 1 else "个人"
            label = f"{model}"
            if brand_name:
                label = f"{brand_name} {model}"
            label += f" [{official}]"
            # 如果标签重复，追加区别后缀
            key = label
            while key in self._drive_label_map:
                key = f"{label} #{i}"
            self._drive_opts.append({"value": key, "label": label})
            self._drive_label_map[key] = d

        return self.async_show_form(
            step_id="drive_list",
            data_schema=vol.Schema({
                vol.Required("drive_index"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._drive_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={
                "desc": f"共找到 {len(self._all_drives)} 个驱动，请选择要添加的设备"
            }
        )

    # ------------------------------------------------------------------
    #  保存：获取驱动详情 → 解析 data.commands → 写入库 → 重载
    # ------------------------------------------------------------------

    async def _save_drive(self, drive_data: dict) -> FlowResult:
        """获取驱动详情，解析data中的commands，保存为红外remote实体"""
        drive_id = drive_data.get("driveId")
        if not drive_id:
            _LOGGER.error("驱动数据缺少driveId")
            return self.async_abort(reason="cloud_fetch_failed")

        # 1. 获取驱动详情（可能包装在 {code, msg, data: {...}} 中）
        detail = await self._api_get(f"/rc/app/drive/{drive_id}")
        _LOGGER.debug("驱动 %s 详情原始响应: %s", drive_id, str(detail)[:300])

        commands = {}

        if detail:
            # 尝试穿透常见 API 包装层找到实际的 drive 对象
            drive_obj = detail
            if "code" in detail and isinstance(detail.get("data"), dict):
                # 包装格式: { code, msg, data: { categoryId, ..., data: "<json>", ... } }
                drive_obj = detail["data"]

            # 从 drive 对象中提取 data 字段（JSON 字符串）
            data_field = drive_obj.get("data", "")

            if isinstance(data_field, str) and data_field.strip():
                try:
                    data_obj = json.loads(data_field)
                    commands = data_obj.get("commands", {})
                except json.JSONDecodeError:
                    _LOGGER.warning("驱动 %s 的data字段不是有效JSON: %s…", drive_id, data_field[:120])
            elif isinstance(data_field, dict):
                # data 字段本身已经是字典对象
                commands = data_field.get("commands", {})

        if not commands:
            _LOGGER.warning("未能从驱动 %s 提取到commands，将创建空按键的遥控器", drive_id)

        # 3. 构建设备信息
        library = self.hass.data[DOMAIN].setdefault("library", {"devices": {}})
        parent_app_serial = self.config_entry.data.get("app_serial", "unknown")

        # 唯一序列号（融合父网关串号 + driveId）
        serial = f"IR_{parent_app_serial}_{drive_id}"

        model_name = drive_data.get("modelName", "未知型号")
        brand_name = drive_data.get("brand", {}).get("brandName", "")
        device_name = f"Sanytron {brand_name} {model_name}" if brand_name else f"Sanytron {model_name}"

        device_info = {
            "serial_number": serial,
            "device_key": f"sanytron_{drive_id}_{parent_app_serial}",
            "name": device_name,
            "buttons": commands,
            "source": "api_drive",
            "parent_app_serial": parent_app_serial,
        }

        # 4. 写入 HA store
        library["devices"][serial] = device_info
        await self.hass.data[DOMAIN]["store"].async_save(library)

        # 5. 更新 config_entry 数据
        new_data = dict(self.config_entry.data)
        new_data.setdefault("devices", {})
        new_data["devices"][serial] = device_info
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # 6. 重载配置条目以创建新的remote实体
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )

        _LOGGER.info("成功挂载红外设备: %s (%d个按键)", device_name, len(commands))
        return self.async_create_entry(title=f"已挂载: {device_name}", data={})
