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
    """前端调用 send_command 时，翻译为真实红外长码并广播"""
    hass = call.hass
    entity_id = call.data["entity_id"]
    ir_code = call.data["button"]
    library = hass.data[DOMAIN].get("library", {})
    
    device_key = entity_id.replace("remote.", "") if entity_id.startswith("remote.") else entity_id
    serial = None
    device_data = {}
    
    for s, d in library.get("devices", {}).items():
        if d.get("device_key") == device_key or s.lower() in device_key.lower():
            serial = s
            device_data = d
            break
            
    if not serial:
        _LOGGER.warning("未找到设备: %s", entity_id)
        return

    buttons = device_data.get("buttons", {})
    actual_ir_code = buttons.get(ir_code, ir_code)

    hass.bus.async_fire(f"{DOMAIN}/control_command", {
        "serial_number": serial,
        "button": actual_ir_code,
        "timestamp": datetime.utcnow().isoformat(),
    })

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
    """供 App 按需拉取完整红外码本的接口"""
    entity_id = msg["entity_id"]
    library = hass.data[DOMAIN].get("library", {})
    
    device_key = entity_id.replace("remote.", "")
    target_data = None
    
    for s, d in library.get("devices", {}).items():
        if d.get("device_key") == device_key or s.lower() in device_key.lower():
            target_data = d
            break
            
    if not target_data:
        connection.send_error(msg["id"], "not_found", f"未找到对应实体: {entity_id}")
        return
        
    connection.send_result(msg["id"], {
        "entity_id": entity_id,
        "serial_number": target_data.get("serial_number"),
        "parent_app_serial": target_data.get("parent_app_serial"),
        "ir_codes": target_data.get("buttons", {})
    })