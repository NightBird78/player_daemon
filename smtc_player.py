import asyncio
from config import SMTC_SOCKET
from base_player import BasePlayer
import utils
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

    def get_meta(self):
        return {
            "title": self.Metadata.get("title", "Unknown"),
            "artist": self.Metadata.get("artist", ["Unknown"])[0],
        }

    def update_smtc(self):
        updater = self.smtc.display_updater
        updater.music_properties.title = self.Metadata.get("title", "Unknown")
        updater.music_properties.artist = self.Metadata.get("artist", ["Unknown"])[0]
        updater.update()

        status_map = {
            "Playing": MediaPlaybackStatus.PLAYING,
            "Paused": MediaPlaybackStatus.PAUSED,
            "Stopped": MediaPlaybackStatus.STOPPED,
        }
        self.smtc.playback_status = status_map.get(
            self.PlaybackStatus, MediaPlaybackStatus.CLOSED
        )

    async def play_current(self):
        url = self.get_current_url()
        if not url:
            return

        self.Metadata = await utils.fetch_metadata(url)

        if not self.proc:
            self.init_mpv(url)
            # todo investigate
            self.mpv.send({"command": ["client_name"]})
            self.mpv.send({"command": ["cycle", "pause"]})
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        await self.async_play_pause(broadcast=False)
        self.update_smtc()

    async def async_play_pause(self, ws_client=None, broadcast=None):
        self.mpv.send({"command": ["cycle", "pause"]})
        self.PlaybackStatus = (
            "Paused" if self.PlaybackStatus == "Playing" else "Playing"
        )

        self.update_smtc()
        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

    async def async_next(self, *, ws_client=None):
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        res = None
        if self.mode == "active":
            if self.active_index + 1 < len(self.active_queue):
                self.active_index += 1
                await self.play_current()
                res = {"current": self.active_queue[self.active_index]}
            else:
                self.active_queue.clear()
                self.active_index = -1
                if self.passive_queue:
                    self.mode = "passive"
                    return await self.async_next(ws_client=ws_client)
                else:
                    return await self.async_stop(ws_client)
        else:
            if self.passive_index + 1 < len(self.passive_queue):
                self.passive_index += 1
                await self.play_current()
                res = {"current": self.passive_queue[self.passive_index]}
            else:
                return await self.async_stop(ws_client)

        self.update_smtc()
        await self.broadcast_state(
            "Next", ws_client=ws_client, additional=res, update_queue=True
        )

    async def async_stop(self, ws_client=None):
        self.mpv.send({"command": ["quit"]})
        self.proc = None
        self.PlaybackStatus = "Stopped"
        self.update_smtc()
        await self.broadcast_state("Stop", ws_client=ws_client, update_queue=True)
