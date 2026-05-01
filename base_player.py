import asyncio
from collections import deque
from utils import fetch_metadata
from server import ws_broadcast


class BasePlayer:
    def __init__(self):
        self.active_queue = deque()
        self.passive_queue = deque()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.PlaybackStatus = "Stopped"
        self.Metadata = {"title": "wait for", "artist": ["queue"]}

    async def broadcast_state(self, action_name, ws_client=None):
        meta = {
            "title": self.Metadata.get("title", ""),
            "artist": self.Metadata.get("artist", [""])[0]
            if isinstance(self.Metadata.get("artist"), list)
            else "",
        }
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
                "metadata": meta,
            },
            ws_client,
        )

    def get_current_url(self):
        if self.mode == "active" and 0 <= self.active_index < len(self.active_queue):
            return self.active_queue[self.active_index]
        if self.mode == "passive" and 0 <= self.passive_index < len(self.passive_queue):
            return self.passive_queue[self.passive_index]
        return None
