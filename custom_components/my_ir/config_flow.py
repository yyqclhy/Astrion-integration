from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
import voluptuous as vol
from .const import DOMAIN
import logging
import json
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "http://192.168.0.210:8081/pro-api"

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
    """API驱动的新设备添加流程（不需要头认证）"""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        # 步骤1: 库
        self._depot_id = None
        self._depot_name = None
        # 步骤2: 设备分类
        self._category_id = None
        self._category_name = None
        # 步骤3: 品牌
        self._brand_id = None
        self._brand_name = None
        # 步骤4: 驱动列表（分页收集）
        self._all_drives = []

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
            self._depot_id = user_input["depot_id"]
            self._depot_name = user_input.get("depot_name", self._depot_id)
            _LOGGER.info("已选择库: %s (%s)", self._depot_name, self._depot_id)
            return await self.async_step_category()

        data = await self._api_get("/rc/app/depot/list")
        depots = self._extract_list(data)

        if not depots:
            return self.async_abort(reason="cloud_fetch_failed")

        # 构建选择器: { depotId: depotName }
        depot_map = {}
        for d in depots:
            did = d.get("depotId") or d.get("id")
            dname = d.get("depotName") or d.get("name") or "未知库"
            if did:
                depot_map[did] = dname

        return self.async_show_form(
            step_id="depot",
            data_schema=vol.Schema({
                vol.Required("depot_id"): vol.In(depot_map)
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
            self._category_id = user_input["category_id"]
            self._category_name = user_input.get("category_name", self._category_id)
            _LOGGER.info("已选择分类: %s (%s)", self._category_name, self._category_id)
            return await self.async_step_brand()

        data = await self._api_get("/rc/app/category/list")
        categories = self._extract_list(data)

        if not categories:
            return self.async_abort(reason="cloud_fetch_failed")

        cat_map = {}
        for c in categories:
            cid = c.get("categoryId") or c.get("id") or c.get("category_id")
            cname = c.get("categoryName") or c.get("name") or "未知分类"
            if cid:
                cat_map[cid] = cname

        return self.async_show_form(
            step_id="category",
            data_schema=vol.Schema({
                vol.Required("category_id"): vol.In(cat_map)
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
            self._brand_id = user_input["brand_id"]
            self._brand_name = user_input.get("brand_name", self._brand_id)
            _LOGGER.info("已选择品牌: %s (%s)", self._brand_name, self._brand_id)
            return await self.async_step_drive_list()

        data = await self._api_get("/rc/app/brand/all")
        brands = self._extract_list(data)

        if not brands:
            return self.async_abort(reason="cloud_fetch_failed")

        brand_map = {}
        for b in brands:
            bid = b.get("brandId") or b.get("id")
            bname = b.get("brandName") or b.get("name") or "未知品牌"
            if bid:
                brand_map[bid] = bname

        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({
                vol.Required("brand_id"): vol.In(brand_map)
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
            selected_idx = user_input["drive_index"]
            if 0 <= selected_idx < len(self._all_drives):
                return await self._save_drive(self._all_drives[selected_idx])
            return await self.async_step_depot()  # fallback

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
            return self.async_abort(reason="cloud_fetch_failed")

        # 构建选择器
        drive_map = {}
        for i, d in enumerate(self._all_drives):
            brand_name = d.get("brand", {}).get("brandName", "")
            model = d.get("modelName", "未知型号")
            official = "官方" if d.get("isOfficial") == 1 else "个人"
            label = f"{model}"
            if brand_name:
                label = f"{brand_name} {model}"
            label += f" [{official}]"
            drive_map[i] = label

        return self.async_show_form(
            step_id="drive_list",
            data_schema=vol.Schema({
                vol.Required("drive_index"): vol.In(drive_map)
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

        if not commands:
            _LOGGER.warning("驱动 %s 没有提取到commands，将创建空按键的遥控器", drive_id)

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
