import asyncio
from config import SMTC_SOCKET
from base_player import BasePlayer
from winsdk.windows.media import MediaPlaybackType

from winsdk.windows.media.playback import MediaPlayer
from winsdk.windows.media import MediaPlaybackStatus, SystemMediaTransportControlsButton


class Stop:
    pass


class SMTCPlayer(BasePlayer):
    def __init__(self, loop):
        super().__init__(SMTC_SOCKET)
        self._dummy_player = MediaPlayer()
        self.smtc = self._dummy_player.system_media_transport_controls

        self.smtc.is_play_enabled = True
        self.smtc.is_pause_enabled = True
        self.smtc.is_next_enabled = True

        self.smtc.display_updater.type = MediaPlaybackType.MUSIC
        self.smtc.display_updater.update()

        self.smtc.add_button_pressed(self._handle_button_press)
        self.loop = loop

    def _handle_button_press(self, sender, args):
        if args.button in (
            SystemMediaTransportControlsButton.PLAY,
            SystemMediaTransportControlsButton.PAUSE,
        ):
            asyncio.run_coroutine_threadsafe(self.async_play_pause(), self.loop)
        elif args.button == SystemMediaTransportControlsButton.NEXT:
            asyncio.run_coroutine_threadsafe(self.async_next(), self.loop)

    def set_meta(self, title, artist):
        if not isinstance(artist, list):
            artist = [artist]
        self.Metadata["title"] = title
        self.Metadata["artist"] = artist

    def get_meta(self):
        return {
            "title": self.Metadata.get("title", "Unknown"),
            "artist": self.Metadata.get("artist", ["Unknown"]),
        }

    def update_widget(self, meta=None, **kw):
        self.set_meta(meta["title"], meta["artist"])
        updater = self.smtc.display_updater
        metadata = self.get_meta()
        updater.music_properties.title = metadata["title"]
        updater.music_properties.artist = ", ".join(metadata["artist"])
        updater.update()

        status_map = {
            "Playing": MediaPlaybackStatus.PLAYING,
            "Paused": MediaPlaybackStatus.PAUSED,
            "Stopped": MediaPlaybackStatus.STOPPED,
        }
        self.smtc.playback_status = status_map.get(
            self.PlaybackStatus, MediaPlaybackStatus.CLOSED
        )

    @property
    def mpv_download_url(self) -> str:
        return "https://github.com/zhongfly/mpv-winbuild/releases/download/2026-05-22-db73857997/mpv-x86_64-20260522-git-db73857997.7z"
