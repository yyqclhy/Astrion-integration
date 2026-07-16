from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import storage, config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.components import websocket_api
import voluptuous as vol
import asyncio
from datetime import datetime
import json
import glob
import os
import logging
from .const import DOMAIN, HARMONY_CONF_PATTERN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.library"
PLATFORMS = ["remote", "select", "button"]

# ====================== 1. 核心初始化 ======================
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    _LOGGER.info("[Startup] async_setup called! config=%s", config)
    
    # 延迟导入，避免模块加载时的依赖问题
    from homeassistant.components.http import HomeAssistantView
    from homeassistant.components import websocket_api

    class HarmonyConfigView(HomeAssistantView):
        """提供 Harmony Hub 配置文件的 HTTP API 端点

        在 HA 配置目录中查找 harmony_*.conf 文件并返回其 JSON 内容。
        供 Lovelace 卡片获取 Harmony Hub 的活动、设备和命令列表。
        """
        url = "/api/astrion/harmony_config"
        name = "api:astrion:harmony_config"
        requires_auth = True

        def __init__(self, hass):
            self.hass = hass

        def _find_all_harmony_confs(self):
            """在配置目录中寻找所有 harmony_*.conf 文件"""
            config_dir = self.hass.config.config_dir
            pattern = os.path.join(config_dir, HARMONY_CONF_PATTERN)
            files = sorted(glob.glob(pattern))
            return files

        async def get(self, request):
            """处理 GET 请求 — 返回所有 Harmony Hub 的配置文件内容"""
            conf_files = await self.hass.async_add_executor_job(self._find_all_harmony_confs)

            if not conf_files:
                return self.json(
                    {"error": "No harmony_*.conf files found in config directory"},
                    status_code=404
                )

            try:
                def read_all_files():
                    hubs = []
                    for path in conf_files:
                        _LOGGER.info("Reading Harmony config file: %s", path)
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        basename = os.path.basename(path)
                        hub_name = basename.replace("harmony_", "").replace(".conf", "")
                        hubs.append({
                            "hub_name": hub_name,
                            "source_file": basename,
                            "config": data
                        })
                    return hubs

                hubs = await self.hass.async_add_executor_job(read_all_files)
                return self.json({"hubs": hubs})

            except Exception as e:
                _LOGGER.error("Failed to read Harmony config file: %s", e)
                return self.json({"error": str(e)}, status_code=500)

    hass.http.register_view(HarmonyConfigView(hass))
    
    # 【关键】注册 WebSocket 处理器（必须在 config_entry 存在之前就注册，否则首次添加集成时 App 消息无处理器）
    _LOGGER.info("[Startup] Registering WebSocket handlers…")
    websocket_api.async_register_command(hass, websocket_submit_pair_data)
    websocket_api.async_register_command(hass, websocket_get_device_codes)
    websocket_api.async_register_command(hass, websocket_get_harmony_config)
    _LOGGER.info("[Startup] WebSocket handlers registered successfully!")

    # 监听 APK 通过 fire_event 上报的导航列表
    async def _handle_navigate_list_upload(event):
        """APK 上报导航列表 → 更新 store → 通知 select 实体"""
        data = event.data
        serial = data.get("serial_number")
        pages = data.get("pages", [])
        if not serial or not pages:
            return
        library = hass.data.setdefault(DOMAIN, {}).setdefault("library", {"devices": {}})
        gateways = library.setdefault("gateways", {})
        gateways.setdefault(serial, {})["pages"] = pages
        await hass.data[DOMAIN]["store"].async_save(library)
        _LOGGER.info("Gateway %s navigate list uploaded: %s", serial, pages)
        hass.bus.async_fire(f"{DOMAIN}/navigate_list_updated", {
            "serial_number": serial,
            "pages": pages,
        })

    hass.bus.async_listen(f"{DOMAIN}/navigate_list_upload", _handle_navigate_list_upload)

    # 监听 APK 上报的页面访问（反向触发自动化）
    async def _handle_page_visited(event):
        """APK 页面访问上报

        - source="user": 用户主动切换 → A-Select 触发自动化
        - source="auto": HA 命令的回包 → A-Select 静默等待复位
        """
        data = event.data
        serial = data.get("serial_number")
        page = data.get("page")
        source = data.get("source", "user")
        if not serial or not page:
            return
        # 存储当前页
        library = hass.data.setdefault(DOMAIN, {}).setdefault("library", {"devices": {}})
        gateways = library.setdefault("gateways", {})
        gateways.setdefault(serial, {})["current_page"] = page
        await hass.data[DOMAIN]["store"].async_save(library)
        _LOGGER.info("Gateway %s page visited: %s (source=%s)", serial, page, source)
        # A-Select: 是否触发自动化取决于 source  |  B-Select: 同步当前值
        refs = hass.data.get(DOMAIN, {}).get("_selects", {}).get(serial, {})
        nav = refs.get("navigate")
        sc  = refs.get("scene")
        if nav:
            await nav.trigger_from_apk(page, source)
        if sc:
            sc.sync_from_apk(page)

    hass.bus.async_listen(f"{DOMAIN}/page_visited", _handle_page_visited)
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """初始化配置条目"""
    store = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["library"] = await store.async_load() or {"devices": {}}

    # 冗余注册 WebSocket 处理器（如果 async_setup 已注册，这是无操作）
    websocket_api.async_register_command(hass, websocket_submit_pair_data)
    websocket_api.async_register_command(hass, websocket_get_device_codes)
    websocket_api.async_register_command(hass, websocket_get_harmony_config)

    # 加载遥控器实体平台 + 网关场景选择器
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # 注册红外服务
    hass.services.async_register(DOMAIN, "discover_all", handle_discover_all)
    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("button"): cv.string,
        })
    )
    return True

# ====================== 2. 卸载与设备删除 ======================
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and len(hass.config_entries.async_entries(DOMAIN)) == 1:
        hass.services.async_remove(DOMAIN, "discover_all")
        hass.services.async_remove(DOMAIN, "send_command")
    return unload_ok

async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """允许在设备页面通过 UI 删除特定红外设备"""
    if DOMAIN not in hass.data or "library" not in hass.data[DOMAIN]:
        return False
    library = hass.data[DOMAIN]["library"]
    devices = library.setdefault("devices", {})
    serial = None

    for ident in device_entry.identifiers:
        if ident[0] == DOMAIN:
            serial = ident[1]
            break

    if serial and serial in devices:
        # 只允许删除属于当前网关条目的设备，避免跨网关误删
        if devices[serial].get("parent_app_serial") != config_entry.data.get("app_serial"):
            return False
        devices.pop(serial, None)
        await hass.data[DOMAIN]["store"].async_save(library)
        
        new_data = dict(config_entry.data)
        if "devices" in new_data and serial in new_data["devices"]:
            new_data["devices"].pop(serial, None)
            hass.config_entries.async_update_entry(config_entry, data=new_data)
            
        _LOGGER.info("Successfully removed device via integration page: %s", serial)
        return True
    return False

# ====================== 3. 服务触发逻辑 ======================
@callback
def handle_discover_all(call: ServiceCall) -> None:
    call.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
        "code": "DISCOVER_ALL",
        "mode": "discover_all",
        "timestamp": datetime.utcnow().isoformat(),
        "source": "service_call"
    })

@callback
def handle_send_command(call: ServiceCall) -> None:
    """红外实体直接使用父网关串号发送控制命令"""
    hass = call.hass
    entity_id = call.data["entity_id"]
    ir_code = call.data["button"]

    # 获取实体状态对象
    state = hass.states.get(entity_id)
    if not state:
        _LOGGER.warning("Entity does not exist: %s", entity_id)
        return

    # 检查是否是自定义红外实体
    domain, _ = entity_id.split(".", 1)
    if domain != "remote":
        _LOGGER.debug("Not an IR entity: %s", entity_id)
        return

    # 从实体属性获取父级网关串号
    parent_serial = state.attributes.get("parent_app_serial")
    if not parent_serial:
        _LOGGER.warning("IR entity %s has no parent gateway serial", entity_id)
        return

    # 获取按键 IR 码
    buttons = state.attributes.get("supported_keys", {})
    # 按键 IR 码直接用传入的 button 名称
    actual_ir_code = ir_code  # 或根据你的 IR 映射字典转换

    # 直接发送控制命令，不再判断网关是否存在
    hass.bus.async_fire(f"{DOMAIN}/control_command", {
        "serial_number": parent_serial,
        "button": actual_ir_code,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _LOGGER.info("IR control command sent: %s -> parent gateway %s -> button %s",
                 entity_id, parent_serial, actual_ir_code)

# ====================== 4. WebSocket 接口定义 ======================
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/submit_pair_data",
    vol.Required("code"): cv.string,
    vol.Required("data"): dict,
})
@websocket_api.async_response
async def websocket_submit_pair_data(hass: HomeAssistant, connection, msg):
    """App 上报配对数据的接口（存入发现列表，等待用户在配置流程中选择）"""
    _LOGGER.info("[Pair] Message received! Raw message: %s", str(msg)[:500])
    
    data = msg["data"]
    app_serial = data.get("serial_number")
    _LOGGER.info("[Pair] serial_number=%s, model=%s, full data=%s", app_serial, data.get("model"), str(data)[:300])
    
    if not app_serial:
        _LOGGER.warning(
            "[Pair Error] App reported data missing serial_number, cannot store in discovery list. "
            "Full message: %s", str(msg)[:500]
        )
        connection.send_error(msg["id"], "missing_serial", "Missing serial_number")
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    
    # 查重：App 已存在则无需再次发现
    for entry in entries:
        if entry.data.get("app_serial") == app_serial:
            _LOGGER.info("[Pair] App serial %s already has a config entry, skipping duplicate pairing", app_serial)
            connection.send_result(msg["id"], {"success": True, "message": "App already exists, no need to pair again"})
            return

    # 存入发现列表，等待用户在配置流程中选择
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("discovered_gateways", {})
    
    model = data.get("model") or "IR Gateway"
    hass.data[DOMAIN]["discovered_gateways"][app_serial] = {
        "serial_number": app_serial,
        "model": model,
        "name": data.get("name", ""),
    }
    
    # 触发 bus 事件，方便外部监听（如配置流程自动刷新）
    hass.bus.async_fire(f"{DOMAIN}/gateway_discovered", {
        "serial": app_serial,
        "model": model,
    })
    
    _LOGGER.info("Discovered new gateway: Smart Remote:%s SN:%s (saved to pending list)", model, app_serial)
    connection.send_result(msg["id"], {
        "success": True,
        "serial": app_serial,
        "message": "Gateway added to pending list, please confirm in HA configuration"
    })

@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_device_codes",
    vol.Required("entity_id"): cv.entity_id,
})
@websocket_api.async_response
async def websocket_get_device_codes(hass: HomeAssistant, connection, msg):
    """供 App 按需拉取完整红外码本的接口（增强版）"""
    entity_id = msg["entity_id"]
    library = hass.data[DOMAIN].get("library", {})
    devices = library.get("devices", {})
    
    # 获取搜索用的 key（转为小写）
    search_key = entity_id.replace("remote.", "").lower()
    target_data = None

    # 第一步：尝试直接通过小写化的 key 匹配
    for s, d in devices.items():
        stored_key = d.get("device_key", "").lower()
        if stored_key == search_key or s.lower() in search_key:
            target_data = d
            break

    # 第二步：如果第一步失败，通过实体注册表找 unique_id (即 serial)
    if not target_data:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
        # 只要找到了 unique_id，就一定能从 library 里拿出来
        if entry and entry.unique_id in devices:
            target_data = devices[entry.unique_id]

    if not target_data:
        connection.send_error(msg["id"], "not_found", f"Entity not found: {entity_id}")
        return
        
    connection.send_result(msg["id"], {
        "entity_id": entity_id,
        "serial_number": target_data.get("serial_number"),
        "parent_app_serial": target_data.get("parent_app_serial"),
        "ir_codes": target_data.get("buttons", {})
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_harmony_config",
    vol.Optional("entity_id"): cv.string,
})
@websocket_api.async_response
async def websocket_get_harmony_config(hass: HomeAssistant, connection, msg):
    """通过 WebSocket 获取 Harmony Hub 的配置文件内容

    如果传入 entity_id，根据实体的 unique_id 精确匹配对应的配置文件；
    如果不传，返回所有配置文件（兼容旧版）。
    """
    try:
        config_dir = hass.config.config_dir
        pattern = os.path.join(config_dir, HARMONY_CONF_PATTERN)
        all_files = sorted(glob.glob(pattern))

        # 如果传了 entity_id，通过实体注册表查 unique_id 来匹配
        target_unique_id = None
        entity_id = msg.get("entity_id")
        if entity_id:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(hass)
            entry = registry.async_get(entity_id)
            if entry:
                target_unique_id = entry.unique_id
                _LOGGER.debug("Harmony entity %s → unique_id: %s", entity_id, target_unique_id)

        hubs = []
        for path in all_files:
            basename = os.path.basename(path)
            file_id = basename.replace("harmony_", "").replace(".conf", "")

            # 如果指定了 unique_id，只匹配对应文件
            if target_unique_id and file_id != target_unique_id:
                continue

            _LOGGER.info("Reading Harmony config file: %s", path)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            hubs.append({
                "hub_name": file_id,
                "source_file": basename,
                "config": data
            })

        connection.send_result(msg["id"], {"hubs": hubs})

    except Exception as e:
        _LOGGER.error("Failed to read Harmony config file: %s", e)
        connection.send_error(msg["id"], "read_error", str(e))

