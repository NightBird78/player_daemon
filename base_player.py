from server import ws_broadcast
from mpv_ipc import MPV, MPVError
from config import cleanup_socket, NEXT_QUEUE_LEN
from abc import ABC, abstractmethod
import subprocess
import utils
import asyncio
import shutil
import os
import yt_dlp
from pathlib import Path
from queue_manager import QueueManager
import sys


class BasePlayer(ABC):
    def __init__(self, socket):
        self.mpv = MPV(socket)
        self.socket = socket
        self.proc = None

        self.lock = asyncio.Lock()
        self.queue = QueueManager()
        self.PlaybackStatus = "Stopped"
        self.Metadata = {"title": "wait for", "artist": ["queue"]}

        self.queue_list = []

        exists_mpv = shutil.which("mpv")
        if not exists_mpv:
            raise OSError("mpv is not found in system and/or in PATH")
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
                    "mode": self.queue.current_mode,
                    "active_size": len(self.queue.active_queue),
                    "active_index": self.queue.active_index,
                    "passive_size": len(self.queue.passive_queue),
                    "passive_index": self.queue.passive_index,
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

            queue_list_temp = self.queue.get_next_slots(NEXT_QUEUE_LEN)

            errors = False
            for q, v in queue_list_temp.items():
                meta = await utils.fetch_metadata(q)
                if meta is None:
                    errors = True
                    self.queue.remove_corrupted_url(q)
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
        return os.path.join(scripts_dir, "youtube-dl")

    async def init_mpv(self, url):
        cleanup_socket(self.socket)

        self.proc = subprocess.Popen(
            [
                self.mpv_wrapper,
                f"--script-opts=ytdl_hook-ytdl_path={self.yt_dlp_path}",
                "--no-video",
                f"--input-ipc-server={self.socket}",
                "--idle=yes",
                "--volume=50",
                "--msg-level=all=no",
                url,
            ]
        )

        timeout = 5.0
        start_time = asyncio.get_running_loop().time()

        print("Очікування ініціалізації IPC сокету MPV...")

        while True:
            if sys.platform == "win32":
                try:
                    with open(self.socket, "r+b") as f:
                        break
                except FileNotFoundError:
                    pass
            else:
                if os.path.exists(self.socket):
                    break

            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"Процес MPV неочікувано завершився з кодом {self.proc.returncode} під час старту!"
                )

            if asyncio.get_running_loop().time() - start_time > timeout:
                raise TimeoutError(
                    f"Не вдалося дочекатися створення сокету MPV за {timeout} секунд."
                )

            await asyncio.sleep(0.05)

        print("MPV успішно піднято IPC-сервер! Підключення...")

        await self.mpv.connect()

    def get_current_url(self):
        return self.queue.get_current_url()

    async def add_active(self, item):
        if await utils.is_playlist(item):
            return False

        should_play = self.queue.add_active(item)
        if should_play:
            await self.play_current()
        return True

    async def set_active_queue(self, items):
        self.queue.set_active_queue(items)
        await self.play_current()

    async def add_passive(self, item):
        should_play = self.queue.add_passive(item)
        if should_play and self.PlaybackStatus != "Playing":
            await self.play_current()

    async def set_passive_queue(self, items):
        should_play = self.queue.set_passive_queue(items)
        if should_play:
            await self.play_current()

    async def async_shuffle(self, *, ws_client=None):
        is_active = self.queue.current_mode == "active"
        if not is_active and self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        self.queue.shuffle_passive()
        self.queue_list.clear()

        if not is_active:
            await self.async_next(broadcast=False)

        await self.broadcast_state("shuffle", ws_client=ws_client, update_queue=True)

    async def async_play_pause(self, *, ws_client=None, broadcast: bool = True):
        if len(self.queue.active_queue) == 0 and len(self.queue.passive_queue) == 0:
            return
        should_pause = self.PlaybackStatus == "Playing"

        res = await self.mpv.send({"command": ["set_property", "pause", should_pause]})
        if res is dict and res.get("error") and res.get("error") != "success":
            raise MPVError(f"Не вдалося змінити стан паузи: {res.get('error')}")

        self.PlaybackStatus = "Paused" if should_pause else "Playing"

        self.update_widget(
            meta=self.get_meta(),
            additional={"PlaybackStatus": self.PlaybackStatus, "CanGoNext": True},
        )
        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

    async def play_current(self):
        url = self.queue.get_current_url()
        if not url:
            return
        try:
            meta = await utils.fetch_metadata(url)
            if meta is None:
                asyncio.create_task(self.async_next())
                return
            if not self.proc:
                await self.init_mpv(url)
            else:
                await self.mpv.send({"command": ["loadfile", url, "replace"]})
            await self.async_play_pause(broadcast=False)
            self.update_widget(meta=meta, additional={"CanGoNext": True})
        except Exception as e:
            print(f"an error in play_current {e}")

    async def async_next(self, *, broadcast=True, ws_client=None, count=1):
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        self.set_meta("loading", "loading")
        self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})

        next_step = self.queue.advance_next(count)

        if next_step in ("play_active", "play_passive"):
            await self.play_current()

            try:
                self.queue_list = self.queue_list[max(1, count) :]
            except Exception:
                pass

            res = {"current": self.queue.get_current_url()}
            await self.broadcast_state(
                "Next",
                broadcast=broadcast,
                ws_client=ws_client,
                additional=res,
                update_queue=True,
            )
        else:
            await self.async_stop(ws_client=ws_client, broadcast=broadcast)

    async def async_stop(self, *, ws_client=None, broadcast=True):
        try:
            await self.mpv.send({"command": ["quit"]})
        except Exception:
            pass

        self.PlaybackStatus = "Stopped"
        self.set_meta("wait for", "queue")
        self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})

        self.queue.clear()

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
