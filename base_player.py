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
from logger import setup_logger


class BasePlayer(ABC):
    def __init__(self, socket):
        self.mpv = MPV(socket)
        self.socket = socket
        self.proc = None

        self.updater_lock = asyncio.Lock()
        self.queue = QueueManager()
        self.PlaybackStatus = "Stopped"
        self.Metadata = {"title": "wait for", "artist": ["queue"]}

        self.current_retry = 0
        self.max_retry = 3

        self.steps = 15
        self.sleep_time = 1 / self.steps
        self.max_volume = 50

        self.log = setup_logger("player")

        exists_mpv = shutil.which("mpv")
        if not exists_mpv:
            raise OSError("mpv is not found in system and/or in PATH")
        self.log.info(f"found mpv: {exists_mpv}")
        self.mpv_wrapper = exists_mpv

        exists_dlp = shutil.which("yt-dlp")
        if not exists_dlp:
            exists_dlp = self.find_ytdlp()
            dlp = Path(exists_dlp)
            if not dlp.exists():
                raise OSError("yt-dlp is not found in system and/or in PATH")
        self.log.info(f"found youtube-dl: {exists_dlp}")
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
                    "queue": self.queue.queue_list,
                }
                | additional,
                ws_client,
                _only,
            )
            if update_queue:
                asyncio.create_task(self._update_queue())

    async def _update_queue(self):
        async with self.updater_lock:
            self.queue.queue_list.clear()

            queue_list_temp = self.queue.get_next_slots(NEXT_QUEUE_LEN)

            errors = False
            for e in queue_list_temp:
                meta = await utils.fetch_metadata(e["url"])
                if meta is None:
                    errors = True
                    self.queue.remove_corrupted_url(e["url"])
                    self.log.warning(f"WARN: Found error-link {e['url']}")
                    continue
                self.queue.queue_list.append(e | meta)

            if len(self.queue.queue_list) > 0:
                await self.broadcast_state(
                    "queue",
                    type="update",
                    additional={
                        "status": "Loading"
                        if self.get_meta()["title"] == "loading"
                        else self.PlaybackStatus,
                    },
                )
            if errors:
                asyncio.create_task(self._update_queue())

    @staticmethod
    def find_ytdlp():
        module_path = yt_dlp.__file__
        site_packages_dir = os.path.dirname(os.path.dirname(module_path))
        scripts_dir = os.path.join(os.path.dirname(site_packages_dir), "Scripts")
        return os.path.join(scripts_dir, "youtube-dl")

    async def init_mpv(self):
        cleanup_socket(self.socket)

        self.proc = subprocess.Popen(
            [
                self.mpv_wrapper,
                f"--script-opts=ytdl_hook-ytdl_path={self.yt_dlp_path}",
                "--no-video",
                "--pause",
                f"--input-ipc-server={self.socket}",
                "--volume=0",
                "--idle=yes",
                "--msg-level=all=no",
            ]
        )

        timeout = 5.0
        start_time = asyncio.get_running_loop().time()

        self.log.info("Очікування ініціалізації IPC сокету MPV...")

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

        self.log.info("MPV успішно піднято IPC-сервер! Підключення...")
        try:
            await self.mpv.connect()
        except Exception as e:
            self.log.error("error while 'await self.mpv.connect()'", e)

    def get_current_url(self):
        return self.queue.get_current_url()

    async def add_active(self, item, *, ws_client=None):
        if await utils.is_playlist(item):
            return False

        should_play = self.queue.add_active(item)
        if should_play:
            self.set_meta("loading", "loading")
            self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})
            self.PlaybackStatus = "Paused"
            await self.play_current(
                broadcast=ws_client is not None, ws_client=ws_client
            )
        return True

    async def set_active_queue(self, items):
        self.queue.set_active_queue(items)
        await self.play_current()

    async def add_passive(self, item, *, ws_client=None):
        should_play = self.queue.add_passive(item)
        if should_play and self.PlaybackStatus != "Playing":
            self.set_meta("loading", "loading")
            self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})
            self.PlaybackStatus = "Paused"
            await self.play_current(
                broadcast=ws_client is not None, ws_client=ws_client
            )

    async def set_passive_queue(self, items):
        should_play = self.queue.set_passive_queue(items)
        if should_play:
            await self.play_current()

    async def async_shuffle(self, *, ws_client=None):
        is_active = self.queue.current_mode == "active"
        self.queue.shuffle_passive()
        self.queue.queue_list.clear()
        self.set_meta("loading", "loading")
        await self.broadcast_state(
            "shuffle",
            ws_client=ws_client,
            additional={"status": "Loading"},
        )
        if not is_active and self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)

        if not is_active:
            await self.async_next(broadcast=False)

        await self.broadcast_state("shuffle", ws_client=ws_client, update_queue=True)

    async def async_play_pause(self, *, ws_client=None, broadcast: bool = True):
        if len(self.queue.active_queue) == 0 and len(self.queue.passive_queue) == 0:
            return
        should_pause = self.PlaybackStatus == "Playing"

        self.PlaybackStatus = "Paused" if should_pause else "Playing"

        self.update_widget(
            meta=self.get_meta(),
            additional={"PlaybackStatus": self.PlaybackStatus, "CanGoNext": True},
        )
        await self.broadcast_state(
            "PlayPause", ws_client=ws_client, broadcast=broadcast
        )

        if not should_pause:
            # --- UNPAUSE (FADE-IN) ---
            await self.mpv.send({"command": ["set_property", "volume", 0]})

            res = await self.mpv.send({"command": ["set_property", "pause", False]})
            if (
                isinstance(res, dict)
                and res.get("error")
                and res.get("error") != "success"
            ):
                raise MPVError(f"Не вдалося зняти з паузи: {res.get('error')}")

            for i in range(1, self.steps + 1):
                current_vol = int((i / self.steps) * self.max_volume)
                await self.mpv.send(
                    {"command": ["set_property", "volume", current_vol]}
                )
                await asyncio.sleep(self.sleep_time)

        else:
            # --- PAUSE (FADE-OUT) ---
            for i in range(self.steps, -1, -1):
                current_vol = int((i / self.steps) * self.max_volume)
                await self.mpv.send(
                    {"command": ["set_property", "volume", current_vol]}
                )
                await asyncio.sleep(self.sleep_time)

            res = await self.mpv.send({"command": ["set_property", "pause", True]})
            if (
                isinstance(res, dict)
                and res.get("error")
                and res.get("error") != "success"
            ):
                raise MPVError(f"Не вдалося поставити на паузу: {res.get('error')}")

            await self.mpv.send({"command": ["set_property", "volume", 50]})

    async def play_current(self, *, broadcast=True, ws_client=None):
        url = self.queue.get_current_url()
        if not url:
            return
        try:
            meta = await utils.fetch_metadata(url)
            if meta is None:
                asyncio.create_task(self.async_next())
                return

            await self.mpv.send({"command": ["loadfile", url, "replace"]})
            try:
                event = await asyncio.wait_for(
                    self._wait_for_event(["file_loaded", "idle"]), timeout=5.0
                )
                if event.get("type") == "idle":
                    self.log.warning("file load problem, retrying")
                    self.current_retry += 1
                    if self.current_retry > self.max_retry:
                        self.current_retry = 0
                        self.log.warning("reached retry limit, switch to next")
                        return await self.async_next()
                    else:
                        self.log.warning(f"try to play: try {self.current_retry}")
                        return await self.play_current()
            except asyncio.TimeoutError:
                self.log.warning("file load timeout, retrying")
                self.current_retry += 1
                if self.current_retry > self.max_retry:
                    self.current_retry = 0
                    self.log.warning("reached retry limit, switch to next")
                    return await self.async_next()
                else:
                    self.log.warning(f"try to play: try {self.current_retry}")
                    return await self.play_current()
            self.current_retry = 0
            await self._wait_for_event(["playback_restart"], timeout=0)

            self.update_widget(meta=meta, additional={"CanGoNext": True})

            res = {
                "current": self.queue.get_current_url(),
                "status": "Playing",
            }
            await self.broadcast_state(
                "update",
                broadcast=broadcast,
                ws_client=ws_client,
                additional=res,
            )
            await self.async_play_pause(broadcast=False)
        except Exception as e:
            self.log.error(f"an error in play_current {e}")

    async def async_next(self, *, broadcast=True, ws_client=None, count=1):
        self.set_meta("loading", "loading")
        self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})
        await self.broadcast_state(
            "pre_next",
            broadcast=broadcast,
            ws_client=ws_client,
            additional={"status": "Loading"},
            update_queue=False,
        )
        if self.PlaybackStatus == "Playing":
            await self.async_play_pause(broadcast=False)
        next_step = self.queue.advance_next(count)

        if next_step in ("play_active", "play_passive"):
            try:
                self.queue.queue_list = self.queue.queue_list[max(1, count) :]
            except Exception:
                pass

            res = {"current": self.queue.get_current_url(), "status": "Loading"}
            await self.broadcast_state(
                "Next",
                broadcast=broadcast,
                ws_client=ws_client,
                additional=res,
                update_queue=True,
            )
            await self.play_current(broadcast=broadcast)
        else:
            await self.async_stop(ws_client=ws_client, broadcast=broadcast)

    async def async_stop(self, *, ws_client=None, broadcast=True):
        try:
            await self.mpv.send({"command": ["set_property", "pause", True]})
            await self.mpv.send({"command": ["stop"]})
        except Exception:
            pass

        self.PlaybackStatus = "Stopped"
        self.set_meta("wait for", "queue")
        self.update_widget(meta=self.get_meta(), additional={"CanGoNext": False})

        self.queue.clear()

        await self.broadcast_state("Stop/End", ws_client=ws_client, broadcast=broadcast)

    async def _wait_for_event(self, event_types, *, timeout=5.0):
        try:
            while True:
                if timeout > 0:
                    event = await asyncio.wait_for(self.mpv.event_queue.get(), timeout)
                else:
                    event = await self.mpv.event_queue.get()
                    await asyncio.sleep(0.5)
                if event.get("type") in event_types:
                    self.log.debug(f"returning event by {event.get('type')}")
                    return event
                await self.mpv.event_queue.put(event)
        except asyncio.TimeoutError:
            raise

    @abstractmethod
    def get_meta(self):
        raise NotImplementedError()

    @abstractmethod
    def set_meta(self, title, artist):
        raise NotImplementedError()

    @abstractmethod
    def update_widget(self, **kw):
        raise NotImplementedError()
