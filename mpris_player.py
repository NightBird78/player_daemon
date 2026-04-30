import os
import json
import socket
import subprocess
from collections import deque
from aiohttp import web
import aiohttp
from mutagen.easyid3 import EasyID3
import asyncio

from pydbus import SessionBus
from pydbus.generic import signal
from gi.repository import GLib

import gbulb

gbulb.install()

SOCKET = "/tmp/mpv-ipc.sock"
PORT = 8765

bus = SessionBus()
loop = asyncio.get_event_loop()
connected_clients = set()
nloop = asyncio.new_event_loop()


# =========================
# MPV IPC helper
# =========================
class MPV:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def send(self, cmd):
        if not os.path.exists(self.socket_path):
            return

        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(self.socket_path)
            s.send((json.dumps(cmd) + "\n").encode())
            response = s.recv(4096).decode()
            s.close()
            return json.loads(response)
        except Exception as e:
            print("IPC error:", e)
            return None

    def get_property(self, prop):
        cmd = {"command": ["get_property", prop]}
        res = self.send(cmd)
        try:
            if res and res.get("request_id") == 0 or "data" in res:
                return res.get("data")
        except TypeError:
            pass
        return None


# =========================
# Player core
# =========================
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
        self.mpv = MPV(SOCKET)

        self.proc = None

        # queues
        self.active_queue = deque()
        self.passive_queue = deque()

        self.active_index = -1
        self.passive_index = -1

        self.mode = "passive"

        # state
        self.Identity = "YT Python Player"
        self.CanQuit = False
        self.PlaybackStatus = "Stopped"
        self.CanGoNext = False
        self.CanPlay = True
        self.CanPause = True
        self.Metadata = {}

        self.Metadata["xesam:title"] = GLib.Variant("s", "wait for")
        self.Metadata["xesam:artist"] = GLib.Variant("as", ["queue"])

    # =========================
    # MPV lifecycle
    # =========================
    def _start_mpv(self, url):
        if os.path.exists(SOCKET):
            os.remove(SOCKET)

        self.proc = subprocess.Popen(
            ["mpv", "--no-video", f"--input-ipc-server={SOCKET}", url]
        )

    # =========================
    # Resolver (active > passive)
    # =========================
    def _current_source(self):
        if self.active_queue:
            self.mode = "active"
            return self.active_queue[self.active_index]

        if self.passive_queue:
            self.mode = "passive"
            return self.passive_queue[self.passive_index]

        return None

    def play_current(self):
        url = self._current_source()
        if not url:
            return

        if url.endswith(".mp3"):
            try:
                audio = EasyID3(url)

                self.Metadata["xesam:title"] = GLib.Variant(
                    "s", audio.get("title", ["Невідомо"])[0]
                )
                self.Metadata["xesam:artist"] = GLib.Variant(
                    "as", [audio.get("artist", ["Невідомо"])[0]]
                )

                try:
                    self.PropertiesChanged(
                        "org.mpris.MediaPlayer2.Player",
                        {"Metadata": self.Metadata},
                        [],
                    )
                except Exception as e:
                    print(e.__repr__())

            except Exception as e:
                print(f"Помилка: {e}")
        else:
            output = subprocess.check_output(["yt-dlp", "-J", url], text=True)
            data = json.loads(output)

            self.Metadata["xesam:title"] = GLib.Variant("s", data["title"])
            self.Metadata["xesam:artist"] = GLib.Variant("as", [data["uploader"]])

            try:
                self.PropertiesChanged(
                    "org.mpris.MediaPlayer2.Player",
                    {"Metadata": self.Metadata},
                    [],
                )
            except Exception as e:
                print(e.__repr__())

        if not self.proc:
            self._start_mpv(url)
        else:
            self.mpv.send({"command": ["loadfile", url, "replace"]})

        self.PlayPause(broadcast=False)

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

        player.Metadata["xesam:title"] = GLib.Variant("s", "loading")
        player.Metadata["xesam:artist"] = GLib.Variant("as", ["loading"])
        player.PropertiesChanged(
            "org.mpris.MediaPlayer2.Player",
            {"Metadata": player.Metadata, "CanGoNext": False},
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
                            "status": player.PlaybackStatus,
                            "active_size": len(player.active_queue),
                            "active_index": self.active_index,
                            "passive_size": len(player.passive_queue),
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
                    self.Stop()

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
                            "status": player.PlaybackStatus,
                            "active_size": len(player.active_queue),
                            "active_index": self.active_index,
                            "passive_size": len(player.passive_queue),
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
                meta[k.split(":")[1]] = v.__str__()
            asyncio.create_task(
                ws_broadcast(
                    {
                        "type": "action",
                        "action": "PlayPause",
                        "status": player.PlaybackStatus,
                        "active_size": len(player.active_queue),
                        "active_index": self.active_index,
                        "passive_size": len(player.passive_queue),
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
                    "status": player.PlaybackStatus,
                },
                ws_client,
            )
        )

    def Raise(self):
        pass

    def Quit(self):
        self.Stop()
        loop.quit()


player = Player()


# =========================
# YouTube playlist loader
# =========================
def load_youtube_playlist(url):
    output = subprocess.check_output(
        ["yt-dlp", "--flat-playlist", "-J", url],
        text=True,
    )

    data = json.loads(output)

    return [
        f"https://www.youtube.com/watch?v={e['id']}"
        for e in data.get("entries", [])
        if e.get("id")
    ]


# =========================
# WebSocket server
# =========================
async def ws_broadcast(data: dict, _except=None):
    for ws in connected_clients:
        if _except and ws is _except:
            continue
        await ws.send_str(json.dumps(data))


async def poll_proc():
    while True:
        await asyncio.sleep(5)
        if not player.proc:
            continue
        if player.proc.poll() is None:
            await ws_broadcast(
                {
                    "type": "process",
                    "percent": player.mpv.get_property("percent-pos"),
                }
            )
            continue
        player.proc = None
        if player.PlaybackStatus == "Stopped":
            continue

        player.Next()


async def handle_index(request):
    """Віддаємо файл вручну, щоб уникнути помилки sendfile в gbulb"""
    try:
        with open("./index.html", "rb") as f:
            content = f.read()
        return web.Response(body=content, content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="index.html не знайдено", status=404)


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    connected_clients.add(ws)

    meta = {k.split(":")[1]: v.unpack() for k, v in player.Metadata.items()}
    await ws.send_json(
        {
            "type": "action",
            "mode": player.mode,
            "action": "init",
            "status": player.PlaybackStatus,
            "metadata": meta,
            "active_size": len(player.active_queue),
            "active_index": player.active_index,
            "passive_size": len(player.passive_queue),
            "passive_index": player.passive_index,
        }
    )

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                cmd = data.get("cmd")

                # ACTIVE playback
                if cmd == "play":
                    player.add_active(data["url"])

                elif cmd == "active_playlist":
                    items = load_youtube_playlist(data["url"])
                    player.set_active_queue(items)

                # PASSIVE queue
                elif cmd == "playlist":
                    items = load_youtube_playlist(data["url"])
                    player.set_passive_queue(items)

                elif cmd == "add":
                    player.add_passive(data["url"])

                # controls
                elif cmd == "control":
                    if data["action"] == "next":
                        player.Next(ws_client=ws)

                    elif data["action"] == "pause":
                        player.PlayPause(ws_client=ws)

                    elif data["action"] == "stop":
                        player.Stop(ws_client=ws)

                meta = {}
                for k, v in player.Metadata.items():
                    meta[k.split(":")[1]] = v.unpack()
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "response",
                            "mode": player.mode,
                            "status": player.PlaybackStatus,
                            "active_size": len(player.active_queue),
                            "active_index": player.active_index,
                            "passive_size": len(player.passive_queue),
                            "passive_index": player.passive_index,
                            "metadata": meta,
                        }
                    )
                )

    finally:
        connected_clients.remove(ws)
    return ws


async def start_unified_server():
    """Запускає все на одному порту"""
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", websocket_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()


# =========================
# start WS thread
# =========================
loop.create_task(start_unified_server())
loop.create_task(poll_proc())

# =========================
# DBus register
# =========================
bus.publish("org.mpris.MediaPlayer2.MyPythonApp", ("/org/mpris/MediaPlayer2", player))


# =========================
# main loop
# =========================
try:
    loop.run_forever()
except KeyboardInterrupt:
    print("Stopping...")
finally:
    pending = asyncio.all_tasks(loop)

    for task in pending:
        task.cancel()

    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

    loop.close()
