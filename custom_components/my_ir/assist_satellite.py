"""网关语音助手实体：按键录音上行、pipeline 事件转发与播报。"""
from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from homeassistant.components.assist_pipeline import PipelineEventType
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assist_stream import ANNOUNCE_TIMEOUT, assist_manager
from .const import DOMAIN
from .gateway import (
    CAPABILITY_ASSIST_SATELLITE,
    coordinator,
    gateway_device_info,
    signal,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """按网关能力动态创建语音助手实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    sessions = assist_manager(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_ASSIST_SATELLITE,
        "voice",
        async_add_entities,
        lambda: [GatewayAssistSatellite(manager, sessions, serial)],
    )


class GatewayAssistSatellite(AssistSatelliteEntity):
    """没有唤醒词，只能由本地语音键或 HA 动作触发。"""

    _attr_has_entity_name = True
    _attr_translation_key = "assist_satellite"
    _attr_supported_features = (
        AssistSatelliteEntityFeature.ANNOUNCE
        | AssistSatelliteEntityFeature.START_CONVERSATION
    )

    def __init__(self, manager, sessions, serial: str) -> None:
        self._manager = manager
        self._sessions = sessions
        self._serial = serial
        self._pipeline_session_id = None
        # 新会话已受理、但 pipeline 还没真正启动时暂存，收到 RUN_START 后再生效，
        # 避免被打断的旧 pipeline 在取消过程中把结束事件串到新会话上。
        self._pending_pipeline_session_id = None
        self._attr_unique_id = f"{serial}_assist_satellite"
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        return self._manager.has_capability(
            self._serial, CAPABILITY_ASSIST_SATELLITE
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._sessions.register_entity(self._serial, self)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal(self._serial), self.async_write_ha_state
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        self._sessions.unregister_entity(self._serial, self)
        await super().async_will_remove_from_hass()

    def set_pending_pipeline_session(self, session_id: str) -> None:
        """记录待生效的会话，等 pipeline RUN_START 后再转发事件。"""
        self._pending_pipeline_session_id = session_id

    def clear_pipeline_session(self, session_id: str) -> None:
        """会话结束后清除记录，避免迟到事件被转发。"""
        if self._pipeline_session_id == session_id:
            self._pipeline_session_id = None
        if self._pending_pipeline_session_id == session_id:
            self._pending_pipeline_session_id = None

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        return AssistSatelliteConfiguration(
            available_wake_words=[], active_wake_words=[], max_active_wake_words=0
        )

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        """设备不实现唤醒词，只接受空配置。"""

    def _fire_event(self, session_id: str, payload: dict) -> None:
        event = {
            "protocol_version": 1,
            "schema_version": 1,
            "gateway_serial": self._serial,
            "session_id": session_id,
        }
        event.update(payload)
        self.hass.bus.async_fire(f"{DOMAIN}/assist/event", event)

    def _event_payload(self, event: str, **fields) -> dict:
        payload = {"event": event}
        payload.update({key: value for key, value in fields.items() if value is not None})
        return payload

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        """播报并等待 APK 回报播放结束，最多等待 120 秒。"""
        if not self.available:
            raise HomeAssistantError(
                "HA100 is offline or does not support voice assistant"
            )
        session_id = f"announce-{uuid4()}"
        try:
            waiter = self._sessions.begin_announce(self._serial, session_id)
        except ValueError as error:
            raise HomeAssistantError("Another announcement is in progress") from error
        try:
            self._fire_event(session_id, {
                "event": "announce",
                # HA 已把播报地址解析为完整地址，设备侧按需替换为实际可达的服务器地址。
                "url": announcement.media_id,
                "text": announcement.message,
            })
            await asyncio.wait_for(waiter, ANNOUNCE_TIMEOUT)
        except asyncio.TimeoutError as error:
            raise HomeAssistantError("Announcement playback timed out") from error
        finally:
            self._sessions.end_announce(self._serial, session_id)

    async def async_start_conversation(
        self, announcement: AssistSatelliteAnnouncement
    ) -> None:
        """先播报开始语，完成后打开 APK 语音弹窗；不等待录音。"""
        await self.async_announce(announcement)
        self._fire_event(f"start-{uuid4()}", {"event": "start_conversation"})

    def on_pipeline_event(self, event) -> None:
        """把 pipeline 事件转发给 APK；播放结束由 tts_finished 上报。"""
        if (event.type is PipelineEventType.RUN_START
                and self._pending_pipeline_session_id is not None):
            self._pipeline_session_id = self._pending_pipeline_session_id
            self._pending_pipeline_session_id = None
        session_id = self._pipeline_session_id
        if session_id is None:
            return
        data = event.data or {}
        if event.type is PipelineEventType.STT_END:
            output = data.get("stt_output") or {}
            self._fire_event(session_id, self._event_payload(
                "stt_result", text=output.get("text"), language=output.get("language"),
            ))
        elif event.type is PipelineEventType.INTENT_END:
            intent = data.get("intent_output") or {}
            response = intent.get("response") or {}
            speech = response.get("speech") or {}
            plain = speech.get("plain") or {}
            self._fire_event(session_id, self._event_payload(
                "intent_result", text=plain.get("speech"),
            ))
        elif event.type is PipelineEventType.TTS_START:
            self._sessions.mark_tts_pending(self._serial, session_id)
        elif event.type is PipelineEventType.TTS_END:
            # HA 只在 TTS_END 的 tts_output 中给出播放地址，且是 /api/tts_proxy/... 相对路径。
            # 这里原样下发，由 APK 拼接设备实际连接的服务器地址，避免 homeassistant.local 无法解析。
            output = data.get("tts_output") or {}
            url = output.get("url")
            if not url:
                _LOGGER.warning("Gateway %s TTS output has no url", self._serial)
            self._fire_event(session_id, self._event_payload(
                "tts_start", url=url,
            ))
            self._fire_event(session_id, self._event_payload("tts_end"))
        elif event.type is PipelineEventType.ERROR:
            self._fire_event(session_id, self._event_payload(
                "error", code=data.get("code"), message=data.get("message"),
            ))
        elif event.type is PipelineEventType.RUN_END:
            self._fire_event(session_id, self._event_payload("run_end"))
