from collections import deque
from server import ws_broadcast
from mpv_ipc import MPV, MPVError
from config import cleanup_socket, NEXT_QUEUE_LEN
from abc import ABC, abstractmethod
import subprocess
import utils
from itertools import islice
import asyncio
import random
import shutil
import os
import yt_dlp
from pathlib import Path


class BasePlayer(ABC):
    def __init__(self, socket):
        self.mpv = MPV(socket)
        self.socket = socket
        self.proc = None

        self.lock = asyncio.Lock()

        self.active_queue = deque()
        self.passive_queue = deque()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.current_mode = "passive"
        self.PlaybackStatus = "Stopped"
        self.Metadata = {"title": "wait for", "artist": ["queue"]}

        self.queue_list = []

        exists_mpv = shutil.which("mpv")
        if not exists_mpv:
            raise OSError("mpv is not found in system and/or in PATH")
        else:
            print(f"found mpv:        {exists_mpv}")
        self.mpv_wrapper = exists_mpv

        exists_dlp = shutil.which("yt-dlp")

        if not exists_dlp:
            exists_dlp = self.find_ytdlp()
            dlp = Path(exists_dlp)
            if not dlp.exists():
                raise OSError("yt-dlp is not found in system and/or in PATH")
        print(f"found youtube-dl: {exists_dlp}")
        self.yt_dlp_path = exists_dlp

    async def broadcast_state(
        self,
        action_name,
        *,
        type="action",
        ws_client=None,
        broadcast: bool = True,
        additional: dict = {},
        update_queue: bool = False,
        _only=None,
    ):
        if broadcast:
            await ws_broadcast(
                {
                    "type": type,
                    "action": action_name,
                    "status": self.PlaybackStatus,
                    "mode": self.current_mode,
                    "active_size": len(self.active_queue),
                    "active_index": self.active_index,
                    "passive_size": len(self.passive_queue),
                    "passive_index": self.passive_index,
                    "metadata": self.get_meta(),
                    "queue": self.queue_list,
                }
                | additional,
                ws_client,
                _only,
            )
            if update_queue:
                asyncio.create_task(self._update_queue())

    async def _update_queue(self):
        async with self.lock:
            self.queue_list.clear()
            queue_list_temp = {}

            start_active = self.active_index + 1
            queue_list_temp = {
                item: "active"
                for item in islice(
                    self.active_queue, start_active, start_active + NEXT_QUEUE_LEN
                )
            }

            remaining_slots = NEXT_QUEUE_LEN - len(queue_list_temp)
            if remaining_slots > 0:
                start_passive = self.passive_index + 1
                queue_list_temp = queue_list_temp | {
                    item: "passive"
                    for item in islice(
                        self.passive_queue,
                        start_passive,
                        start_passive + remaining_slots,
                    )
                }
            errors = False
            for q, v in queue_list_temp.items():
                meta = await utils.fetch_metadata(q)
                if meta is None:
                    errors = True
                    if q in self.active_queue:
                        self.active_queue.remove(q)
                    if q in self.passive_queue:
                        self.passive_queue.remove(q)
                    print(f"WARN: Found error-link {q}")
                    continue
                self.queue_list.append({"url": q, "type": v} | meta)
            if len(self.queue_list) > 0:
                await self.broadcast_state("queue", type="update")
            if errors:
                asyncio.create_task(self._update_queue())

    @staticmethod
    def find_ytdlp():
        module_path = yt_dlp.__file__
        site_packages_dir = os.path.dirname(os.path.dirname(module_path))
        scripts_dir = os.path.join(os.path.dirname(site_packages_dir), "Scripts")
        exe_path = os.path.join(scripts_dir, "youtube-dl")
        return exe_path

    def init_mpv(self, url):
        cleanup_socket(self.socket)
        self.proc = subprocess.Popen(
            [
                self.mpv_wrapper,
                f"--script-opts=ytdl_hook-ytdl_path={self.yt_dlp_path}",
                "--no-video",
                f"--input-ipc-server={self.socket}",
                "--volume=50",
                "--msg-level=all=no",
                url,
            ]
        )

    def get_current_url(self):
        if self.mode == "active" and 0 <= self.active_index < len(self.active_queue):
            return self.active_queue[self.active_index]
        if self.mode == "passive" and 0 <= self.passive_index < len(self.passive_queue):
            return self.passive_queue[self.passive_index]
        return None

    async def add_active(self, item):
        if await utils.is_playlist(item):
            return False
        self.active_queue.append(item)

        self.mode = "active"
        # self.active_index = len(self.active_queue) - 1
        if self.passive_index == -1 and self.active_index == -1:
            self.active_index = 0
            self.current_mode = "active"
            await self.play_current()
        return True

    async def set_active_queue(self, items):
        self.active_queue = deque(items)
        self.active_index = 0

        self.mode = "active"
        await self.play_current()

    # =========================
    # PASSIVE queue (fallback)
    # =========================
    async def add_passive(self, item):
        self.passive_queue.append(item)

        if self.passive_index == -1:
            if self.mode == "passive" and self.PlaybackStatus != "Playing":
                self.passive_index = 0
                await self.play_current()

    async def set_passive_queue(self, items):
        self.passive_queue = deque(items)

        if self.mode == "passive":
            self.passive_index = 0
            await self.play_current()

    async def async_shuffle(self, *, ws_client=None):
        is_active = self.current_mode == "active"
        if not is_active:
            if self.PlaybackStatus == "Playing":
                await self.async_play_pause(broadcast=False)

        temp_q = self.passive_queue.copy()

        random.shuffle(temp_q)

        self.passive_queue = deque(temp_q)
        self.queue_list.clear()
        self.passive_index = -1
        if not is_active:
            await self.async_next(broadcast=False)

        await self.broadcast_state("shuffle", ws_client=ws_client, update_queue=True)

    async def async_play_pause(self, *, ws_client=None, broadcast: bool = True):
        if len(self.active_queue) == 0 and len(self.passive_queue) == 0:
            return

        if self.PlaybackStatus == "Paused":
            res = self.mpv.send({"command": ["set_property", "pause", False]})
            if res is None:
                pass
            elif res.get("error") is None:
                return await self.async_play_pause(
                    ws_client=ws_client, broadcast=broadcast
                )
            elif res.get("error") != "success":
                raise MPVError(f"Не вдалося поставити на паузу: {res.get('error')}")
        elif self.PlaybackStatus == "Playing":
            res = self.mpv.send({"command": ["set_property", "pause", True]})
            if res is None:
                pass
            elif res.get("error") is None:
                return await self.async_play_pause(
                    ws_client=ws_client, broadcast=broadcast
                )
            elif res.get("error") != "success":
                raise MPVError(f"Не вдалося поставити на паузу: {res.get('error')}")

        self.PlaybackStatus = (
            "Paused" if self.PlaybackStatus == "Playing" else "Playing"
        )

        self.update_widget(
            meta=self.get_meta(),
            additional={"PlaybackStatus": self.PlaybackStatus, "CanGoNext": True},
        )

        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

    async def play_current(self):
        url = (
            self.active_queue[self.active_index]
            if self.mode == "active"
            else self.passive_queue[self.passive_index]
        )
        try:
            meta = await utils.fetch_metadata(url)
            if meta is None:
                asyncio.create_task(self.async_next())
                return

            if not self.proc:
                self.init_mpv(url)
            else:
                self.mpv.send({"command": ["loadfile", url, "replace"]})

            await self.async_play_pause(broadcast=False)
            self.update_widget(meta=meta, additional={"CanGoNext": True})
        except Exception as e:
            print(f"an error in play_current {e}", e.__cause__)

    async def async_next(self, *, broadcast=True, ws_client=None, count=1):
        local_count = max(1, count)
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)
        self.set_meta("loading", "loading")
        self.update_widget(
            meta=self.get_meta(),
            additional={"CanGoNext": False},
        )

        res = {}
        if self.mode == "active":
            self.current_mode = "active"
            if self.active_index + local_count < len(self.active_queue):
                self.active_index += local_count
                await self.play_current()

                try:
                    self.queue_list = self.queue_list[local_count:]
                except:
                    pass

                res = {"current": self.active_queue[self.active_index]}
            else:
                local_count = (self.active_index + local_count) - len(self.active_queue)
                self.active_queue.clear()
                self.active_index = -1

                self.mode = "passive"
                self.current_mode = "passive"

                if self.passive_queue:
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
                    self.queue_list = self.queue_list[local_count:]
                except:
                    pass

                res = {"current": self.passive_queue[self.passive_index]}

            else:
                await self.async_stop(ws_client=ws_client)
                return
        await self.broadcast_state(
            "Next",
            broadcast=broadcast,
            ws_client=ws_client,
            additional=res,
            update_queue=True,
        )

    async def async_stop(self, *, ws_client=None, broadcast=True):
        self.mpv.send({"command": ["quit"]})
        self.PlaybackStatus = "Stopped"

        self.set_meta("wait for", "queue")
        self.update_widget(
            meta=self.get_meta(),
            additional={"CanGoNext": False},
        )
        self.active_queue.clear()
        self.passive_queue.clear()

        self.active_index = -1
        self.passive_index = -1

        await self.broadcast_state("Stop/End", ws_client=ws_client, broadcast=broadcast)

    @abstractmethod
    def get_meta(self):
        raise NotImplementedError()

    @abstractmethod
    def set_meta(self, title, artist):
        raise NotImplementedError()

    @abstractmethod
    def update_widget(self, **kw):
        raise NotImplementedError()
