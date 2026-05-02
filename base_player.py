from collections import deque
from server import ws_broadcast
from mpv_ipc import MPV
from config import cleanup_socket, NEXT_QUEUE_LEN
import subprocess
import utils
from itertools import islice
import asyncio


class BasePlayer:
    def __init__(self, socket):
        self.mpv = MPV(socket)
        self.socket = socket
        self.proc = None

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
                    "mode": self.mode,
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
        self.queue_list.clear()
        queue_list_temp = []
        if len(self.active_queue) > 0:
            if self.active_index + NEXT_QUEUE_LEN + 1 < len(self.active_queue) - 1:
                queue_list_temp.extend(
                    islice(
                        self.active_queue,
                        self.active_index + 1,
                        self.active_index + 1 + NEXT_QUEUE_LEN,
                    )
                )
            else:
                queue_list_temp.extend(
                    islice(self.active_queue, self.active_index + 1, None)
                )
        if len(queue_list_temp) < NEXT_QUEUE_LEN and len(self.passive_queue) > 0:
            if self.passive_index + NEXT_QUEUE_LEN + 1 < len(self.passive_queue) - 1:
                queue_list_temp.extend(
                    islice(
                        self.passive_queue,
                        self.passive_index + 1,
                        self.passive_index + 1 + NEXT_QUEUE_LEN - len(queue_list_temp),
                    )
                )
            else:
                queue_list_temp.extend(
                    islice(self.passive_queue, self.passive_index + 1, None)
                )

        for q in queue_list_temp:
            self.queue_list.append({"url": q} | await utils.fetch_metadata(q))

        if len(self.queue_list) > 0:
            await self.broadcast_state("queue", type="update")

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
