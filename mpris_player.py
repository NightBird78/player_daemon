import subprocess
from gi.repository import GLib
from pydbus.generic import signal
from mpv_ipc import MPV
from base_player import BasePlayer
from utils import fetch_metadata
from config import MPRIS_SOCKET, IDENTITY, cleanup_socket
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
        super().__init__()
        self.mpv = MPV(MPRIS_SOCKET)
        self.proc = None
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
        meta = await fetch_metadata(url)

        if not self.proc:
            cleanup_socket(MPRIS_SOCKET)
            self.proc = subprocess.Popen(
                ["mpv", "--no-video", f"--input-ipc-server={MPRIS_SOCKET}", url]
            )
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        await self.async_play_pause(broadcast=False)
        self._update_mpris_metadata(meta, {"CanGoNext": True})

    # =========================
    # Navigation
    # =========================
    def Next(self):
        asyncio.create_task(self.async_next())

    async def async_next(self, *, ws_client=None):
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        self.Metadata["xesam:title"] = GLib.Variant("s", "loading")
        self.Metadata["xesam:artist"] = GLib.Variant("as", ["loading"])
        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {
                "Metadata": self.Metadata,
                "CanGoNext": False,
                # "PlayBackStatus": self.PlaybackStatus,
            },
            [],
        )
        if self.mode == "active":
            if self.active_index + 1 < len(self.active_queue):
                self.active_index += 1
                await self.play_current()

                (
                    await self.broadcast_state(
                        "Next",
                        ws_client=ws_client,
                        additional={"current": self.active_queue[self.active_index]},
                    ),
                )

            else:
                self.active_queue.clear()
                self.active_index = -1

                if self.passive_queue:
                    self.mode = "passive"
                    await self.async_next(ws_client=ws_client)
                else:
                    await self.async_stop(ws_client=ws_client)

        else:
            if self.passive_index + 1 < len(self.passive_queue):
                self.passive_index += 1
                await self.play_current()

                (
                    await self.broadcast_state(
                        "Next",
                        ws_client=ws_client,
                        additional={"current": self.passive_queue[self.passive_index]},
                    ),
                )

            else:
                await self.async_stop(broadcast=False)

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

        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {
                "PlaybackStatus": self.PlaybackStatus,
                "CanGoNext": False,
                "Metadata": self.Metadata,
            },
            [],
        )

        self.active_queue.clear()
        self.passive_queue.clear()

        self.active_index = -1
        self.passive_index = -1

        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

    def Raise(self):
        pass

    def Quit(self):
        asyncio.create_task(self.async_stop())
