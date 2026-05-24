from collections import deque
import random
from itertools import islice


class QueueManager:
    def __init__(self):
        self.active_queue = deque()
        self.passive_queue = deque()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.current_mode = "passive"

    def clear(self):
        """Повне очищення всіх черг та скидання індексів."""
        self.active_queue.clear()
        self.passive_queue.clear()
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.current_mode = "passive"

    def get_current_url(self):
        """Повертає URL треку, який має відтворюватися зараз."""
        if self.mode == "active" and 0 <= self.active_index < len(self.active_queue):
            return self.active_queue[self.active_index]
        if self.mode == "passive" and 0 <= self.passive_index < len(self.passive_queue):
            return self.passive_queue[self.passive_index]
        return None

    def add_active(self, item) -> bool:
        """Додає один трек до активної черги. Повертає True, якщо треба запустити плеєр."""
        self.active_queue.append(item)
        self.mode = "active"

        if self.passive_index == -1 and self.active_index == -1:
            self.active_index = 0
            self.current_mode = "active"
            return True
        return False

    def set_active_queue(self, items):
        """Перезаписує активну чергу."""
        self.active_queue = deque(items)
        self.active_index = 0
        self.mode = "active"
        self.current_mode = "active"

    def add_passive(self, item) -> bool:
        """Додає один трек до пасивної черги. Повертає True, якщо треба запустити плеєр."""
        self.passive_queue.append(item)
        if self.passive_index == -1 and self.mode == "passive":
            self.passive_index = 0
            return True
        return False

    def set_passive_queue(self, items) -> bool:
        """Перезаписує пасивну чергу. Повертає True, якщо треба запустити плеєр."""
        self.passive_queue = deque(items)
        if self.mode == "passive":
            self.passive_index = 0
            return True
        return False

    def shuffle_passive(self):
        """Перемішує пасивну чергу та скидає її індекс."""
        temp_q = list(self.passive_queue)
        random.shuffle(temp_q)
        self.passive_queue = deque(temp_q)
        self.passive_index = -1

    def advance_next(self, count=1) -> str:
        """
        Зсуває індекси вперед на `count` треків.
        Повертає новий статус черги: 'play_active', 'play_passive' або 'stop'.
        """
        local_count = max(1, count)

        if self.mode == "active":
            self.current_mode = "active"
            if self.active_index + local_count < len(self.active_queue):
                self.active_index += local_count
                return "play_active"
            else:
                remaining_steps = (self.active_index + local_count) - len(
                    self.active_queue
                )
                self.active_queue.clear()
                self.active_index = -1

                self.mode = "passive"
                self.current_mode = "passive"

                if self.passive_queue:
                    return self.advance_next(count=remaining_steps + 1)
                else:
                    return "stop"
        else:
            self.current_mode = "passive"
            if self.passive_index + local_count < len(self.passive_queue):
                self.passive_index += local_count
                return "play_passive"
            else:
                return "stop"

    def remove_corrupted_url(self, url):
        """Видаляє «бите» посилання з усіх черг, якщо воно там є."""
        if url in self.active_queue:
            self.active_queue.remove(url)
        if url in self.passive_queue:
            self.passive_queue.remove(url)

    def get_next_slots(self, limit: int) -> dict:
        """Формує словник {url: 'active'/'passive'} для наступних треків у черзі."""
        slots = {}

        start_active = self.active_index + 1
        for item in islice(self.active_queue, start_active, start_active + limit):
            slots[item] = "active"

        remaining = limit - len(slots)
        if remaining > 0:
            start_passive = self.passive_index + 1
            for item in islice(
                self.passive_queue, start_passive, start_passive + remaining
            ):
                slots[item] = "passive"

        return slots

    def next(self, trackId):
        pass

    def move(self, trackId, _to):
        match _to:
            case "up":
                pass
            case "down":
                pass

    def change(self, trackId, _to):
        match _to:
            case "active":
                pass
            case "passive":
                pass

    def postpone(self, trackId):
        pass

    def remove(self, trackId):
        if trackId in self.passive_queue:
            self.passive_queue.remove(trackId)
            return True, None
        if trackId in self.active_queue:
            self.active_queue.remove(trackId)
            return True, None
        return False, "element not found"
