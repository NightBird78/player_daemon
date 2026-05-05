from gi.repository import GLib
from pydbus.generic import signal
from base_player import BasePlayer
import utils
from config import MPRIS_SOCKET, IDENTITY
import asyncio


class MPRISPlayer(BasePlayer):
    PropertiesChanged = signal()

    dbus = """
    <node>
      <interface name="org.mpris.MediaPlayer2">
        <method name="Raise"/>
        <method name="Quit"/>
        <property name="Identity" type="s" access="read"/>
      </interface>
      <interface name="org.mpris.MediaPlayer2.Player">
        <property name="PlaybackStatus" type="s" access="read"/>
        <property name="Metadata" type="a{sv}" access="read"/>
        <property name="CanGoNext" type="b" access="read"/>
        <property name="CanPlay" type="b" access="read"/>
        <property name="CanPause" type="b" access="read"/>
        <method name="PlayPause"/>
        <method name="Next"/>
        <method name="Stop"/>
      </interface>
    </node>
    """

    def __init__(self):
        super().__init__(MPRIS_SOCKET)
        # state
        self.Identity = IDENTITY
        self.CanGoNext = False
        self.CanPlay = True
        self.CanPause = True
        self.Metadata = {
            "xesam:title": GLib.Variant("s", "wait for"),
            "xesam:artist": GLib.Variant("as", ["queue"]),
        }

    def _update_mpris_metadata(self, meta, additional: dict = {}):
        self.Metadata["xesam:title"] = GLib.Variant("s", meta["title"])
        self.Metadata["xesam:artist"] = GLib.Variant("as", meta["artist"])
        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {"Metadata": self.Metadata} | additional,
            [],
        )

    def get_meta(self):
        return {
            "title": self.Metadata["xesam:title"].unpack(),
            "artist": self.Metadata["xesam:artist"].unpack(),
        }

    async def play_current(self):
        url = (
            self.active_queue[self.active_index]
            if self.mode == "active"
            else self.passive_queue[self.passive_index]
        )
        meta = await utils.fetch_metadata(url)
        if meta is None:
            asyncio.create_task(self.async_next())
            return

        if not self.proc:
            self.init_mpv(url)
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        await self.async_play_pause(broadcast=False)
        self._update_mpris_metadata(meta, {"CanGoNext": True})

    # =========================
    # Navigation
    # =========================
    def Next(self):
        asyncio.create_task(self.async_next())

    async def async_next(self, *, ws_client=None, count=1):
        local_count = max(1, count)
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        self.Metadata["xesam:title"] = GLib.Variant("s", "loading")
        self.Metadata["xesam:artist"] = GLib.Variant("as", ["loading"])
        self._update_mpris_metadata(
            self.get_meta(),
            additional={"CanGoNext": False},
        )

        res = {}
        if self.mode == "active":
            self.current_mode = "active"
            if self.active_index + local_count < len(self.active_queue):
                self.active_index += local_count
                await self.play_current()

                try:
                    self.queue_list.pop(0)
                except:
                    pass

                res = {"current": self.active_queue[self.active_index]}
            else:
                local_count = (self.active_index + local_count) - len(self.active_queue)
                self.active_queue.clear()
                self.active_index = -1

                if self.passive_queue:
                    self.mode = "passive"
                    self.current_mode = "passive"
                    await self.async_next(ws_client=ws_client, count=local_count + 1)
                    return
                else:
                    await self.async_stop(ws_client=ws_client)
                    return

        else:
            self.current_mode = "passive"
            if self.passive_index + local_count < len(self.passive_queue):
                self.passive_index += local_count
                await self.play_current()

                try:
                    self.queue_list.pop(0)
                except:
                    pass

                res = {"current": self.passive_queue[self.passive_index]}

            else:
                await self.async_stop(ws_client=ws_client)
                return
        await self.broadcast_state(
            "Next",
            ws_client=ws_client,
            additional=res,
            update_queue=True,
        )

    # =========================
    # Controls
    # =========================
    def PlayPause(self):
        asyncio.create_task(self.async_play_pause())

    async def async_play_pause(self, *, ws_client=None, broadcast: bool = True):
        if len(self.active_queue) == 0 and len(self.passive_queue) == 0:
            return

        self.mpv.send({"command": ["cycle", "pause"]})

        self.PlaybackStatus = (
            "Paused" if self.PlaybackStatus == "Playing" else "Playing"
        )

        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {"PlaybackStatus": self.PlaybackStatus, "CanGoNext": True},
            [],
        )

        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

    def Stop(self, *, ws_client=None):
        asyncio.create_task(self.async_stop())

    async def async_stop(self, *, ws_client=None, broadcast=True):
        self.mpv.send({"command": ["quit"]})
        self.PlaybackStatus = "Stopped"

        self.Metadata["xesam:title"] = GLib.Variant("s", "wait for")
        self.Metadata["xesam:artist"] = GLib.Variant("as", ["queue"])
        self._update_mpris_metadata(
            self.get_meta(),
            additional={"CanGoNext": False},
        )
        self.active_queue.clear()
        self.passive_queue.clear()

        self.active_index = -1
        self.passive_index = -1

        await self.broadcast_state("Stop/End", ws_client=ws_client, broadcast=broadcast)

    def Raise(self):
        pass

    def Quit(self):
        asyncio.create_task(self.async_stop())
