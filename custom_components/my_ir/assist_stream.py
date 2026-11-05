"""Assist 语音会话管理：把 APK 上行音频桥接到 HA pipeline，并等待播报结束。"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import logging

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
# 播报最多等待 APK 回报播放结束的时间，与协议十三节一致。
ANNOUNCE_TIMEOUT = 120
# 会话开始后没有音频块的超时时间，避免实体长期停留在 listening。
FIRST_CHUNK_TIMEOUT = 3


@dataclass
class _AssistSession:
    """一个网关同一时间只允许一个活动会话。"""

    session_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    first_chunk: asyncio.Event = field(default_factory=asyncio.Event)
    ended: bool = False
    tts_pending: bool = False


class AssistSessionManager:
    """维护语音会话、实体登记和播报等待。"""

    def __init__(self, hass):
        self.hass = hass
        self._entities = {}
        self._sessions = {}
        self._announce_waiters = {}

    def register_entity(self, serial, entity):
        self._entities[serial] = entity

    def unregister_entity(self, serial, entity):
        """注销实体并结束仍未完成的会话。"""
        if self._entities.get(serial) is entity:
            self._entities.pop(serial, None)
        self.abort_gateway(serial)

    def abort_gateway(self, serial):
        """网关离线或实体移除时终止会话，避免 pipeline 一直等待音频。"""
        session = self._sessions.pop(serial, None)
        if session is not None:
            session.ended = True
            session.queue.put_nowait(None)
            # 离线时已开始播放的 TTS 收不到 tts_finished，立即恢复实体状态。
            if session.tts_pending:
                entity = self._entities.get(serial)
                if entity is not None:
                    entity.clear_pipeline_session(session.session_id)
                    entity.tts_response_finished()
            self.hass.bus.async_fire(f"{DOMAIN}/assist/event", {
                "protocol_version": 1, "schema_version": 1,
                "gateway_serial": serial, "session_id": session.session_id,
                "event": "session_cancelled",
            })
        for waiter in list(self._announce_waiters.get(serial, {}).values()):
            if not waiter.done():
                waiter.set_exception(
                    HomeAssistantError("Gateway went offline before announcement finished")
                )
        self._announce_waiters.pop(serial, None)

    def _check_live(self, message):
        """校验网关在线、boot_id 与语音能力。"""
        from .gateway import CAPABILITY_ASSIST_SATELLITE, coordinator

        gateway = coordinator(self.hass)
        serial = message["gateway_serial"]
        if serial not in gateway.active:
            raise ValueError("gateway_not_ready")
        live = gateway.live(serial)
        if not live:
            raise ValueError("gateway_not_ready")
        if live.get("boot_id") != message["boot_id"]:
            raise ValueError("stale_session")
        if not gateway.has_capability(serial, CAPABILITY_ASSIST_SATELLITE):
            raise ValueError("gateway_not_ready")

    async def start_session(self, message):
        serial = message["gateway_serial"]
        self._check_live(message)
        entity = self._entities.get(serial)
        if entity is None:
            raise ValueError("internal_error")
        # 新会话直接打断上一条：结束旧音频流并清除旧绑定，
        # HA 会在新 pipeline 启动时自动取消旧 pipeline（协议 13.1）。
        previous = self._sessions.get(serial)
        if previous is not None:
            previous.ended = True
            previous.queue.put_nowait(None)
            entity.clear_pipeline_session(previous.session_id)
        session_id = message["payload"]["session_id"]
        session = _AssistSession(session_id)
        self._sessions[serial] = session
        entity.set_pending_pipeline_session(session_id)
        self.hass.async_create_task(self._run(serial, entity, session))
        self.hass.async_create_task(self._finish_without_audio(session))
        return {"accepted": True}

    async def _finish_without_audio(self, session):
        try:
            await asyncio.wait_for(session.first_chunk.wait(), FIRST_CHUNK_TIMEOUT)
        except asyncio.TimeoutError:
            session.ended = True
            session.queue.put_nowait(None)

    async def _run(self, serial, entity, session):
        async def stream():
            while True:
                chunk = await session.queue.get()
                if chunk is None:
                    return
                yield chunk

        try:
            # 会话在启动前已被新会话打断时直接退出，避免旧 pipeline 事件串到新会话。
            if self._sessions.get(serial) is not session:
                return
            await entity.async_accept_pipeline_from_satellite(stream())
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Gateway %s assist pipeline failed", serial)
            raise
        finally:
            if (self._sessions.get(serial) is session
                    and not session.tts_pending):
                self._sessions.pop(serial, None)
                entity.clear_pipeline_session(session.session_id)
            _LOGGER.debug("Gateway %s assist session finished", serial)

    async def audio_chunk(self, message):
        self._check_live(message)
        serial = message["gateway_serial"]
        payload = message["payload"]
        session = self._sessions.get(serial)
        if session is None or session.ended or session.session_id != payload["session_id"]:
            raise ValueError("stale_session")
        session.queue.put_nowait(base64.b64decode(payload["audio"]))
        session.first_chunk.set()
        return {"accepted": True}

    async def session_end(self, message):
        self._check_live(message)
        session = self._sessions.get(message["gateway_serial"])
        if session is not None and session.session_id == message["payload"]["session_id"]:
            session.ended = True
            session.queue.put_nowait(None)
        return {"accepted": True}

    async def tts_finished(self, message):
        """APK 播放结束后恢复实体 idle，并唤醒等待中的播报。"""
        self._check_live(message)
        serial = message["gateway_serial"]
        session_id = message["payload"]["session_id"]
        session = self._sessions.get(serial)
        if session is not None and session.session_id == session_id:
            self._sessions.pop(serial, None)
            entity = self._entities.get(serial)
            if entity is not None:
                entity.clear_pipeline_session(session_id)
                entity.tts_response_finished()
        self._resolve_announce(serial, session_id)
        return {"accepted": True}

    def mark_tts_pending(self, serial, session_id):
        """pipeline 结束前已开始播放 TTS 时保留会话，等 APK 回报播放结束。"""
        session = self._sessions.get(serial)
        if session is None or session.session_id != session_id:
            return
        session.tts_pending = True
        self.hass.async_create_task(self._tts_timeout(serial, session_id))

    async def _tts_timeout(self, serial, session_id):
        await asyncio.sleep(ANNOUNCE_TIMEOUT)
        session = self._sessions.get(serial)
        if session is None or session.session_id != session_id or not session.tts_pending:
            return
        self._sessions.pop(serial, None)
        _LOGGER.warning("Gateway %s TTS playback did not finish in time", serial)
        entity = self._entities.get(serial)
        if entity is not None:
            entity.clear_pipeline_session(session_id)
            entity.tts_response_finished()

    def begin_announce(self, serial, session_id):
        """登记一次播报等待；同一网关只允许一个播报。"""
        waiters = self._announce_waiters.setdefault(serial, {})
        if waiters:
            raise ValueError("assist_busy")
        waiter = asyncio.get_running_loop().create_future()
        waiters[session_id] = waiter
        return waiter

    def _resolve_announce(self, serial, session_id):
        """按会话标识结束播报等待，避免被 pipeline TTS 误唤醒。"""
        waiters = self._announce_waiters.get(serial)
        if not waiters:
            return
        waiter = waiters.pop(session_id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(True)
        if not waiters:
            self._announce_waiters.pop(serial, None)

    def end_announce(self, serial, session_id):
        waiters = self._announce_waiters.get(serial)
        if waiters is not None:
            waiters.pop(session_id, None)
            if not waiters:
                self._announce_waiters.pop(serial, None)


def assist_manager(hass):
    """返回所有网关共用的语音会话管理器。"""
    shared = hass.data.setdefault(DOMAIN, {})
    if "assist_sessions" not in shared:
        shared["assist_sessions"] = AssistSessionManager(hass)
    return shared["assist_sessions"]
