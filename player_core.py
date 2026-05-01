import subprocess
from collections import deque
from gi.repository import GLib
from pydbus.generic import signal
from mpv_ipc import MPV
from utils import fetch_metadata
from config import SOCKET, IDENTITY, cleanup_socket
from server import ws_broadcast
import asyncio


class Player:
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
        self.mpv = MPV()
        self.proc = None
        self.active_queue = deque()
        self.passive_queue = deque()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        # state
        self.Identity = IDENTITY
        self.CanQuit = False
        self.PlaybackStatus = "Stopped"
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

    def play_current(self):
        url = (
            self.active_queue[self.active_index]
            if self.mode == "active"
            else self.passive_queue[self.passive_index]
        )
        meta = fetch_metadata(url)
        self._update_mpris_metadata(meta, {"CanGoNext": True})

        if not self.proc:
            cleanup_socket()
            self.proc = subprocess.Popen(
                ["mpv", "--no-video", f"--input-ipc-server={}", url]
            )
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        self.PlaybackStatus = "Playing"

    # =========================
    # ACTIVE queue (priority)
    # =========================
    def add_active(self, item):
        self.active_queue.append(item)

        self.mode = "active"
        # self.active_index = len(self.active_queue) - 1
        if self.passive_index == -1 and self.active_index == -1:
            self.active_index = 0
            self.play_current()

    def set_active_queue(self, items):
        self.active_queue = deque(items)
        self.active_index = 0

        self.mode = "active"
        self.play_current()

    # =========================
    # PASSIVE queue (fallback)
    # =========================
    def add_passive(self, item):
        self.passive_queue.append(item)

        if self.mode == "passive" and self.PlaybackStatus != "Playing":
            # self.passive_index = len(self.passive_queue) - 1
            self.play_current()

    def set_passive_queue(self, items):
        self.passive_queue = deque(items)

        if self.mode == "passive":
            self.passive_index = 0
            self.play_current()

    # =========================
    # Navigation
    # =========================
    def Next(self, *, ws_client=None):
        if self.PlaybackStatus == "Playing":
            self.PlayPause(broadcast=False)

        self.Metadata["xesam:title"] = GLib.Variant("s", "loading")
        self.Metadata["xesam:artist"] = GLib.Variant("as", ["loading"])
        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {"Metadata": self.Metadata, "CanGoNext": False},
            [],
        )
        if self.mode == "active":
            if self.active_index + 1 < len(self.active_queue):
                self.active_index += 1
                self.play_current()

                meta = {}
                for k, v in self.Metadata.items():
                    meta[k.split(":")[1]] = v.unpack()
                asyncio.create_task(
                    ws_broadcast(
                        {
                            "type": "action",
                            "action": "Next",
                            "from": "active",
                            "current": self.active_queue[self.active_index],
                            "status": self.PlaybackStatus,
                            "active_size": len(self.active_queue),
                            "active_index": self.active_index,
                            "passive_size": len(self.passive_queue),
                            "passive_index": self.passive_index,
                            "metadata": meta,
                        },
                        ws_client,
                    )
                )
            else:
                self.active_queue.clear()
                self.active_index = -1

                if self.passive_queue:
                    self.mode = "passive"
                    self.Next()
                else:
                    self.Stop(ws_client=ws_client)

        else:
            if self.passive_index + 1 < len(self.passive_queue):
                self.passive_index += 1
                self.play_current()

                meta = {}
                for k, v in self.Metadata.items():
                    meta[k.split(":")[1]] = v.unpack()
                asyncio.create_task(
                    ws_broadcast(
                        {
                            "type": "action",
                            "action": "Next",
                            "from": "passive",
                            "current": self.passive_queue[self.passive_index],
                            "status": self.PlaybackStatus,
                            "active_size": len(self.active_queue),
                            "active_index": self.active_index,
                            "passive_size": len(self.passive_queue),
                            "passive_index": self.passive_index,
                            "metadata": meta,
                        },
                        ws_client,
                    )
                )
            else:
                self.Stop()

    # =========================
    # Controls
    # =========================
    def PlayPause(self, *, ws_client=None, broadcast: bool = True):
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

        if broadcast:
            meta = {}
            for k, v in self.Metadata.items():
                meta[k.split(":")[1]] = v.unpack()
            asyncio.create_task(
                ws_broadcast(
                    {
                        "type": "action",
                        "action": "PlayPause",
                        "status": self.PlaybackStatus,
                        "active_size": len(self.active_queue),
                        "active_index": self.active_index,
                        "passive_size": len(self.passive_queue),
                        "passive_index": self.passive_index,
                        "metadata": meta,
                    },
                    ws_client,
                )
            )

    def Stop(self, *, ws_client=None):
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

        asyncio.create_task(
            ws_broadcast(
                {
                    "type": "action",
                    "action": "Stop/End",
                    "status": self.PlaybackStatus,
                },
                ws_client,
            )
        )

    def Raise(self):
        pass

    def Quit(self):
        self.Stop()
        # loop.quit()
