import subprocess
import asyncio
from mpv_ipc import MPV
from config import SMTC_SOCKET, cleanup_socket
from base_player import BasePlayer
from utils import fetch_metadata
from winsdk.windows.media import (
    SystemMediaTransportControls,
    SystemMediaTransportControlsProperty,
)
from winsdk.windows.media import MediaPlaybackStatus


class SMTCPlayer(BasePlayer):
    def __init__(self):
        super().__init__()
        self.mpv = MPV()
        self.proc = None
        # Ініціалізація SMTC (потрібне вікно або фоновий потік)
        self.smtc = SystemMediaTransportControls.get_for_current_view()
        self.smtc.is_play_enabled = True
        self.smtc.is_pause_enabled = True
        self.smtc.is_next_enabled = True
        self.smtc.add_button_pressed(self._handle_button_press)

    def _handle_button_press(self, sender, args):
        from winsdk.windows.media import SystemMediaTransportControlsButton

        if (
            args.button == SystemMediaTransportControlsButton.PLAY
            or args.button == SystemMediaTransportControlsButton.PAUSE
        ):
            self.PlayPause()
        elif args.button == SystemMediaTransportControlsButton.NEXT:
            self.Next()

    def update_smtc(self):
        updater = self.smtc.display_updater
        updater.type = 1  # Music
        updater.music_properties.title = self.Metadata["title"]
        updater.music_properties.artist = self.Metadata["artist"][0]
        updater.update()

        status_map = {
            "Playing": MediaPlaybackStatus.PLAYING,
            "Paused": MediaPlaybackStatus.PAUSED,
            "Stopped": MediaPlaybackStatus.STOPPED,
        }
        self.smtc.playback_status = status_map.get(
            self.PlaybackStatus, MediaPlaybackStatus.CLOSED
        )

    def play_current(self):
        url = self.get_current_url()
        if not url:
            return
        self.Metadata = fetch_metadata(url)

        if not self.proc:
            cleanup_socket()
            self.proc = subprocess.Popen(
                ["mpv", "--no-video", f"--input-ipc-server={SMTC_SOCKET}", url]
            )
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        self.PlaybackStatus = "Playing"
        self.update_smtc()

    def Next(self, ws_client=None):
        # Аналогічна логіка перемикання як в MPRIS
        # ... (код ідентичний Next в MPRISPlayer)
        self.play_current()
        asyncio.create_task(self.broadcast_state("Next", ws_client))

    def PlayPause(self, ws_client=None):
        self.mpv.send({"command": ["cycle", "pause"]})
        self.PlaybackStatus = (
            "Paused" if self.PlaybackStatus == "Playing" else "Playing"
        )
        self.update_smtc()
        asyncio.create_task(self.broadcast_state("PlayPause", ws_client))

    def Stop(self, ws_client=None):
        self.mpv.send({"command": ["quit"]})
        self.PlaybackStatus = "Stopped"
        self.update_smtc()
        asyncio.create_task(self.broadcast_state("Stop", ws_client))
