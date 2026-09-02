"""网关选择器 — 每个网关设备两个 select 实体

A-Select (导航事件 / Navigate Event): 复位型触发器，用于 HA 自动化事件触发
B-Select (导航动作 / Navigate Action): 持久状态型，用于用户手动控制 + 展示当前页面

挂在网关设备（parent_app_serial）上，与各个红外遥控器设备平级。
"""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN
from .gateway import coordinator, signal
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

SENTINEL = "—"


# ====================== 平台入口 ======================

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """为每个网关创建 A + B 两个 select 实体"""
    parent_serial = entry.data.get("app_serial")
    if not parent_serial:
        return

    gw = hass.data.get(DOMAIN, {}).get("library", {}).get("gateways", {}).get(parent_serial, {})

    pages = gw.get("pages")
    sel_nav = GatewayNavigateSelect(hass, parent_serial, pages)
    sel_scene = GatewaySceneSelect(hass, parent_serial, pages, gw.get("current_page"))

    async_add_entities([sel_nav, sel_scene], True)

    refs = hass.data.setdefault(DOMAIN, {}).setdefault("_selects", {})
    refs[parent_serial] = {"navigate": sel_nav, "scene": sel_scene}


# ====================== A-Select: 快捷导航（复位型） ======================

class GatewayNavigateSelect(SelectEntity):
    """A-Select (导航事件 / Navigate Event): 复位型触发器

    - options 首位永远有 "—"（等待位）
    - APK 通过 trigger_from_apk() 触发：设为 page → 0.3s 后回 "—"
    - 用户手动选非 "—"：通知 APK 跳转（navigate_to）
    - 用户选 "—"：无操作
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, serial: str, pages: list[str] | None):
        self._serial = serial
        self._gateway = coordinator(hass)
        self._attr_unique_id = f"{serial}_navigate"
        # 中英文名称通过 translations/select 翻译文件配置
        self._attr_translation_key = "navigate"

        self._attr_device_info = _device_info(serial)

        self._pages = _ensure_sentinel(pages or [])
        self._current_page = SENTINEL
        self._reset_task = None
        self._syncing = False

    # ---- options / current ----

    @property
    def options(self) -> list[str]:
        return self._pages

    @property
    def current_option(self) -> str | None:
        return self._current_page

    @property
    def available(self) -> bool:
        return self._gateway.has_capability(self._serial, "navigation_control")

    # ---- 用户手动选 / 自动化执行 → 通知 APK + 自动复位 ----

    async def async_select_option(self, option: str) -> None:
        if not self.available:
            raise HomeAssistantError("Gateway is offline or navigation is unsupported")
        if option == SENTINEL:
            return
        if self._syncing:
            return

        self._current_page = option
        self.async_write_ha_state()

        self.hass.bus.async_fire(f"{DOMAIN}/navigate_to", {
            "serial_number": self._serial,
            "target_page": option,
        })

        self._schedule_reset()

    # ---- APK 反向触发入口（不通知 APK，但同样复位） ----

    async def trigger_from_apk(self, page: str, source: str = "user"):
        """APK 上报 page_visited

        - source="user": 用户主动切换 → 触发自动化 + 自动复位
        - source="auto": HA 自己发命令后的回包 → 不复位触发，静默回到 SENTINEL
        """
        if page == SENTINEL:
            return

        # Only accept APK values that are present in the current options.
        if page not in self._pages:
            _LOGGER.warning(
                "Gateway %s ignored APK page not in options: %s",
                self._serial,
                page,
            )
            return

        if source == "auto":
            # 这是 HA 发出的 navigate_to 的回包，不重复触发自动化
            # 但当前值可能是用户/自动化设的，需要等它复位完成
            return

        # source == "user": 用户主动在 APK 上切换 → 正常触发自动化
        self._syncing = True
        try:
            # 当前不是等待位时，先立即复位到 —，确保每个事件从 — 出发
            if self._current_page != SENTINEL:
                self._current_page = SENTINEL
                self.async_write_ha_state()
                await asyncio.sleep(0)  # 让出事件循环，确保 — 状态变更已被 HA 处理

            self._current_page = page
            self.async_write_ha_state()
            self._schedule_reset()
        finally:
            self._syncing = False

    # ---- 复位 ----

    def _schedule_reset(self):
        if self._reset_task:
            self._reset_task.cancel()
        self._reset_task = self.hass.loop.call_later(0.3, self._reset)

    def _reset(self, *_):
        if self._current_page != SENTINEL:
            self._current_page = SENTINEL
            self.async_write_ha_state()

    # ---- 监听 navigate_list_updated (共享 same options) ----

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}/navigate_list_updated",
                self._on_nav_list
            )
        )

    async def _on_nav_list(self, event):
        if event.data.get("serial_number") != self._serial:
            return
        pages = _ensure_sentinel(event.data.get("pages", []))
        if pages != self._pages:
            self._pages = pages
            self.async_write_ha_state()


# ====================== B-Select: 导航动作 / Navigate Action（不复位） ======================

class GatewaySceneSelect(SelectEntity):
    """B-Select (导航动作 / Navigate Action): 持久状态型

    - 无 "—"，不复位
    - 用户手动选 → 通知 APK 跳转（navigate_to）
    - APK 同步当前页面 → 更新 current_option
    - options 与 A-Select 共享同一个列表
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, serial: str,
                 pages: list[str] | None, current: str | None):
        self._serial = serial
        self._gateway = coordinator(hass)
        self._attr_unique_id = f"{serial}_scene"
        # 中英文名称通过 translations/select 翻译文件配置
        self._attr_translation_key = "scene"

        self._attr_device_info = _device_info(serial)

        self._pages = [p for p in (pages or []) if p != SENTINEL]
        self._current = current
        self._state_sync_flag = False  # True=自己写的state，False=外部(Scene)写的

    # ---- options / current ----

    @property
    def options(self) -> list[str]:
        return self._pages

    @property
    def current_option(self) -> str | None:
        return self._current

    @property
    def available(self) -> bool:
        return self._gateway.has_capability(self._serial, "navigation_control")

    # ---- 用户手动选 → 通知 APK ----

    async def async_select_option(self, option: str) -> None:
        if not self.available:
            raise HomeAssistantError("Gateway is offline or navigation is unsupported")
        self._current = option
        self._state_sync_flag = True
        self.async_write_ha_state()

        self.hass.bus.async_fire(f"{DOMAIN}/navigate_to", {
            "serial_number": self._serial,
            "target_page": option,
        })

    # ---- APK 同步当前值 action----

    def sync_from_apk(self, value: str):
        """APK 上报 page_visited → 静默更新当前值（不触发 navigate_to）"""
        # Only accept APK values that are present in the current options.
        if value not in self._pages:
            _LOGGER.warning(
                "Gateway %s ignored APK scene value not in options: %s",
                self._serial,
                value,
            )
            return
        self._current = value
        self._state_sync_flag = True
        self.async_write_ha_state()

    # ---- 监听 navigate_list_updated (与 A-Select 共享) ----

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal(self._serial), self.async_write_ha_state)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}/navigate_list_updated",
                self._on_list
            )
        )
        # 监听 state_changed，捕获 HA Scene 直接写状态的场景
        self.async_on_remove(
            self.hass.bus.async_listen(
                "state_changed",
                self._on_external_state_change
            )
        )

    async def _on_list(self, event):
        if event.data.get("serial_number") != self._serial:
            return
        pages = [p for p in event.data.get("pages", []) if p != SENTINEL]
        if pages != self._pages:
            self._pages = pages
            self.async_write_ha_state()

    async def _on_external_state_change(self, event):
        """捕获 HA Scene 或外部直接写状态：如果非本实体跳过，如果是自己写的跳过，否则发 navigate_to"""
        if event.data.get("entity_id") != self.entity_id:
            return
        if self._state_sync_flag:
            # 我们自己写的 state，复位标志
            self._state_sync_flag = False
            return
        # 外部（HA Scene）改变的 state → 通知 APK 跳转
        new_state = event.data.get("new_state")
        if new_state and new_state.state:
            self._current = new_state.state
            _LOGGER.info("Gateway %s external state change: %s", self._serial, new_state.state)
            self.hass.bus.async_fire(f"{DOMAIN}/navigate_to", {
                "serial_number": self._serial,
                "target_page": new_state.state,
            })


# ====================== 工具函数 ======================

def _device_info(serial: str) -> dict:
    return {
        "identifiers": {(DOMAIN, serial)},
        "name": f"Smart Remote SN:{serial}",
        "manufacturer": "Sanytron",
        "model": "IR Gateway",
    }


def _ensure_sentinel(pages: list[str]) -> list[str]:
    clean = [p for p in pages if p != SENTINEL]
    return [SENTINEL] + clean
