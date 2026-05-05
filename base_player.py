from collections import deque
from server import ws_broadcast
from mpv_ipc import MPV
from config import cleanup_socket, NEXT_QUEUE_LEN
from abc import ABC, abstractmethod
import subprocess
import utils
from itertools import islice
import asyncio
import random


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

    def init_mpv(self, url):
        cleanup_socket(self.socket)
        self.proc = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                f"--input-ipc-server={self.socket}",
                "--volume=50",
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
        self.active_queue.append(item)

        self.mode = "active"
        # self.active_index = len(self.active_queue) - 1
        if self.passive_index == -1 and self.active_index == -1:
            self.active_index = 0
            self.current_mode = "active"
            await self.play_current()

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

        self.passive_index = -1
        if not is_active:
            await self.async_next(broadcast=False)

        await self.broadcast_state("shuffle", ws_client=ws_client, update_queue=True)

    @abstractmethod
    def get_meta(self):
        raise NotImplementedError()

    @abstractmethod
    def set_meta(self, title, artist):
        raise NotImplementedError()

    @abstractmethod
    async def play_current(self):
        raise NotImplementedError()

    @abstractmethod
    async def async_next(self, *, broadcast=True, ws_client=None, count=1):
        raise NotImplementedError()

    @abstractmethod
    async def async_play_pause(self, *, ws_client=None, broadcast: bool = True):
        raise NotImplementedError()

    @abstractmethod
    async def async_stop(self, *, ws_client=None, broadcast=True):
        raise NotImplementedError()
