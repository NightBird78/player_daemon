from gi.repository import GLib
from pydbus.generic import signal
from base_player import BasePlayer
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

    def update_widget(self, meta, additional: dict = {}, **kw):
        self.set_meta(meta["title"], meta["artist"])
        self.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {"Metadata": self.Metadata} | additional,
            [],
        )

    def set_meta(self, title, artist):
        if isinstance(artist, list):
            artist = artist[0]
        self.Metadata["xesam:title"] = GLib.Variant("s", title)
        self.Metadata["xesam:artist"] = GLib.Variant("as", [artist])

    def get_meta(self):
        return {
            "title": self.Metadata["xesam:title"].unpack(),
            "artist": self.Metadata["xesam:artist"].unpack(),
        }

    # =========================
    # Navigation
    # =========================
    def Next(self):
        asyncio.create_task(self.async_next())

    # =========================
    # Controls
    # =========================
    def PlayPause(self):
        asyncio.create_task(self.async_play_pause())

    def Stop(self, *, ws_client=None):
        asyncio.create_task(self.async_stop())

    def Raise(self):
        pass

    def Quit(self):
        asyncio.create_task(self.async_stop())
