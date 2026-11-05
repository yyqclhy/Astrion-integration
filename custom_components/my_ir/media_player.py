"""网关扬声器媒体实体：播放 HA 媒体与 TTS，并上报音量状态。"""
from __future__ import annotations

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    async_process_play_media_url,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gateway import (
    CAPABILITY_MEDIA_PLAYER,
    MEDIA_COMMAND_PAUSE,
    MEDIA_COMMAND_PLAY,
    MEDIA_COMMAND_RESUME,
    MEDIA_COMMAND_SET_MUTE,
    MEDIA_COMMAND_SET_VOLUME,
    MEDIA_COMMAND_STOP,
    coordinator,
    gateway_device_info,
    signal,
)

# 与协议 7.4 的 url 长度上限一致。
MAX_MEDIA_URL_BYTES = 2048


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """按网关能力动态创建扬声器实体。"""
    serial = entry.data.get("app_serial")
    if not serial:
        return

    manager = coordinator(hass)
    manager.register_capability_entity_adder(
        serial,
        CAPABILITY_MEDIA_PLAYER,
        "speaker",
        async_add_entities,
        lambda: [GatewaySpeaker(manager, serial)],
    )


class GatewaySpeaker(MediaPlayerEntity):
    """网关扬声器；播放状态、音量和静音以 APK 上报为准。"""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "media_player"
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, manager, serial: str) -> None:
        self._manager = manager
        self._serial = serial
        self._attr_unique_id = f"{serial}_media_player"
        self._attr_device_info = gateway_device_info(serial)

    @property
    def available(self) -> bool:
        # 首次媒体状态上报前也必须可用，否则第三方播放器（如 Music Assistant）
        # 会因实体不可用而读不到属性并直接忽略该实体。
        return self._manager.has_capability(
            self._serial, CAPABILITY_MEDIA_PLAYER
        )

    @property
    def state(self) -> MediaPlayerState | None:
        media = self._manager.media_status(self._serial)
        state = media.get("state")
        if state == "playing":
            return MediaPlayerState.PLAYING
        if state == "paused":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    async def async_media_play(self) -> None:
        """继续播放当前被暂停的媒体。"""
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_RESUME, {}
        )

    async def async_media_pause(self) -> None:
        """暂停当前媒体播放。"""
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_PAUSE, {}
        )

    async def async_media_stop(self) -> None:
        """停止当前媒体播放。"""
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_STOP, {}
        )

    @property
    def volume_level(self) -> float | None:
        value = self._manager.media_status(self._serial).get("volume_level")
        return value / 100 if isinstance(value, int) else None

    @property
    def is_volume_muted(self) -> bool | None:
        return self._manager.media_status(self._serial).get("muted")

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """把媒体解析成绝对地址后下发播放命令。"""
        if media_id.startswith("media-source://"):
            media = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            url = media.url
            mime_type = media.mime_type or media_type
        else:
            url = media_id
            mime_type = media_type
        url = async_process_play_media_url(
            self.hass, url, allow_relative_url=True
        )
        if len(url.encode("utf-8")) > MAX_MEDIA_URL_BYTES:
            raise HomeAssistantError("Media URL exceeds 2048 bytes")
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_PLAY, {"url": url, "mime_type": mime_type}
        )

    async def async_set_volume_level(self, volume: float) -> None:
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_SET_VOLUME,
            {"volume": max(0, min(100, round(volume * 100)))},
        )

    async def async_mute_volume(self, mute: bool) -> None:
        await self._manager.send_media_control(
            self._serial, MEDIA_COMMAND_SET_MUTE, {"muted": mute}
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal(self._serial), self.async_write_ha_state
            )
        )
