from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import storage, config_validation as cv, device_registry as dr
from homeassistant.components import websocket_api
import voluptuous as vol
import asyncio
from datetime import datetime
import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.library"

# ====================== 1. 核心初始化 ======================
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """初始化配置条目"""
    store = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["library"] = await store.async_load() or {"devices": {}}

    # 注册所有的 WebSocket 接口
    websocket_api.async_register_command(hass, websocket_submit_pair_data)
    websocket_api.async_register_command(hass, websocket_get_device_codes)

    # 加载遥控器实体平台
    await hass.config_entries.async_forward_entry_setups(entry, ["remote"])
    
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
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["remote"])
    if unload_ok and len(hass.config_entries.async_entries(DOMAIN)) == 1:
        hass.services.async_remove(DOMAIN, "discover_all")
        hass.services.async_remove(DOMAIN, "send_command")
    return unload_ok

async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
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
            
        _LOGGER.info("通过集成页面成功移除设备: %s", serial)
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
        _LOGGER.warning("实体不存在: %s", entity_id)
        return

    # 检查是否是自定义红外实体
    domain, _ = entity_id.split(".", 1)
    if domain != "remote":
        _LOGGER.debug("不是红外实体: %s", entity_id)
        return

    # 从实体属性获取父级网关串号
    parent_serial = state.attributes.get("parent_app_serial")
    if not parent_serial:
        _LOGGER.warning("红外实体 %s 没有父网关串号", entity_id)
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
    _LOGGER.info("红外控制命令发送: %s -> 父网关 %s -> 按键 %s",
                 entity_id, parent_serial, actual_ir_code)

# ====================== 4. WebSocket 接口定义 ======================
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/submit_pair_data",
    vol.Required("code"): cv.string,
    vol.Required("data"): dict,
})
@websocket_api.async_response
async def websocket_submit_pair_data(hass: HomeAssistant, connection, msg):
    """App 上报配对数据的接口（纯网关注册，不生成遥控实体）"""
    data = msg["data"]
    app_serial = data.get("serial_number")
    
    if not app_serial:
        connection.send_error(msg["id"], "missing_serial", "缺少 serial_number")
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    
    # 1. 查重：App 已存在则无需重复配对
    for entry in entries:
        if entry.data.get("app_serial") == app_serial:
            connection.send_result(msg["id"], {"success": True, "message": "App 已存在，无需重复配对"})
            return

    # 2. 找空闲条目
    target_entry = None
    for entry in entries:
        if not entry.data.get("app_serial"):
            target_entry = entry
            break
            
    if target_entry:
        new_data = dict(target_entry.data)
        new_data["app_serial"] = app_serial
        
        hass.config_entries.async_update_entry(
            target_entry, 
            title=f"Sanytron 网关: {app_serial}",
            data=new_data
        )
        
        # 将 App 注册为底层的物理设备网关
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=target_entry.entry_id,
            identifiers={(DOMAIN, app_serial)},
            name=f"Sanytron {data.get('name', '红外网关')}",
            manufacturer="Sanytron",
            model="IR Gateway App",
        )

        connection.send_result(msg["id"], {"success": True, "serial": app_serial})
        
        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "message": f"网关配对成功！\n名称：{data.get('name')}",
                "title": "Sanytron IR - 发现新网关",
                "notification_id": f"my_ir_pair_{app_serial}"
            }
        )
    else:
        connection.send_error(msg["id"], "no_pending_entry", "没有等待配对的空闲条目")

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
        connection.send_error(msg["id"], "not_found", f"未找到对应实体: {entity_id}")
        return
        
    connection.send_result(msg["id"], {
        "entity_id": entity_id,
        "serial_number": target_data.get("serial_number"),
        "parent_app_serial": target_data.get("parent_app_serial"),
        "ir_codes": target_data.get("buttons", {})
    })