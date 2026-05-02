from collections import deque
from server import ws_broadcast


class BasePlayer:
    def __init__(self):
        self.active_queue = deque()
        self.passive_queue = deque()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.is_starting = False
        self.playlist_processing = False
        self.PlaybackStatus = "Stopped"
        self.Metadata = {"title": "wait for", "artist": ["queue"]}

    async def broadcast_state(
        self,
        action_name,
        *,
        ws_client=None,
        broadcast: bool = True,
        additional: dict = {},
    ):
        if broadcast:
            await ws_broadcast(
                {
                    "type": "action",
                    "action": action_name,
                    "status": self.PlaybackStatus,
                    "mode": self.mode,
                    "active_size": len(self.active_queue),
                    "active_index": self.active_index,
                    "passive_size": len(self.passive_queue),
                    "passive_index": self.passive_index,
                    "metadata": self.get_meta(),
                }
                | additional,
                ws_client,
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
