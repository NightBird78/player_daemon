import random


class QueueManager:
    def __init__(self):
        self.active_queue = []
        self.passive_queue = []
        self.queue_list = []
        self.active_index = -1
        self.passive_index = -1
        self.mode = "passive"
        self.current_mode = "passive"

    def clear(self):
        """Повне очищення всіх черг та скидання індексів."""
        self.active_queue.clear()
        self.passive_queue.clear()
        self.queue_list.clear()
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

    def set_active_queue(self, items: list):
        """Перезаписує активну чергу."""
        self.active_queue = items.copy()
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

    def set_passive_queue(self, items: list) -> bool:
        """Перезаписує пасивну чергу. Повертає True, якщо треба запустити плеєр."""
        self.passive_queue = items.copy()
        if self.mode == "passive":
            self.passive_index = 0
            return True
        return False

    def shuffle_passive(self):
        """Перемішує пасивну чергу та скидає її індекс."""
        random.shuffle(self.passive_queue)
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
        try:
            self.active_queue.remove(url)
        except ValueError:
            pass
        try:
            self.passive_queue.remove(url)
        except ValueError:
            pass

    def get_next_slots(self, limit: int) -> list[dict]:
        """Формує словник {url: 'active'/'passive'} для наступних треків у черзі."""
        slots = []

        start_active = self.active_index + 1
        for item in self.active_queue[start_active : start_active + limit]:
            slots.append({"url": item, "type": "active"})

        remaining = limit - len(slots)
        if remaining > 0:
            start_passive = self.passive_index + 1
            for item in self.passive_queue[start_passive : start_passive + remaining]:
                slots.append({"url": item, "type": "passive"})

        return slots

    def next(self, trackId, _in):
        try:
            match _in:
                case "active":
                    idx = self.active_queue.index(trackId, self.active_index + 1)
                    self.active_queue.pop(idx)
                    self.active_queue.insert(self.active_index + 1, trackId)
                case "passive":
                    idx = self.passive_queue.index(trackId, self.passive_index + 1)
                    self.passive_queue.pop(idx)
                    self.active_queue.insert(self.active_index + 1, trackId)
                case _:
                    return False, f"cannot find data '{_in}'"
        except ValueError:
            return False, f"Track not found in '{_in}'"
        self.mode = "active"
        return True, None

    def move(self, trackId, _to, _in):
        res = False
        cause = "internal conflict"
        movable = None
        index = None
        match _in:
            case "active":
                movable = self.active_queue
                index = self.active_index
            case "passive":
                movable = self.passive_queue
                index = self.passive_index
        if movable is None:
            return False, f"cannot find data '{_in}'"
        try:
            match _to:
                case "up":
                    idx = movable.index(trackId, index + 1)
                    if idx == index + 1:
                        res, cause = False, "Element is already at the top"
                    else:
                        movable.pop(idx)
                        movable.insert(idx - 1, trackId)
                        res, cause = True, None
                case "down":
                    idx = movable.index(trackId, index + 1)
                    if idx >= len(movable) - 1:
                        res, cause = False, "Element is already at the bottom"
                    else:
                        movable.pop(idx)
                        movable.insert(idx + 1, trackId)
                        res, cause = True, None
        except ValueError:
            cause = f"no this element in {_in}"

        return res, cause

    def change(self, trackId, _to):
        res = False
        cause = "internal conflict"
        match _to:
            case "active":
                try:
                    idx = self.passive_queue.index(trackId, self.passive_index + 1)
                    self.passive_queue.pop(idx)
                    self.active_queue.append(trackId)
                    self.mode = "active"
                    res, cause = True, None
                except ValueError:
                    res, cause = False, "no this element in passive"
            case "passive":
                try:
                    idx = self.active_queue.index(trackId, self.active_index + 1)
                    self.active_queue.pop(idx)
                    self.passive_queue.insert(self.passive_index + 1, trackId)
                    res, cause = True, None
                except ValueError:
                    res, cause = False, "no this element in active"

        return res, cause

    def postpone(self, trackId, _in):
        if _in == "active":
            return False, "postpone accessed only in 'passive'"
        r = random.randint(self.passive_index + 5, len(self.passive_queue) + 1)
        try:
            idx = self.passive_queue.index(trackId, self.passive_index + 1)
            self.passive_queue.pop(idx)
            self.passive_queue.insert(r, trackId)
            for e in self.queue_list:
                if e["url"] == trackId and e["type"] == "passive":
                    self.queue_list.remove(e)
                    return True, None
        except ValueError:
            pass
        return False, "internal conflict"

    def remove(self, trackId, _in):
        try:
            match _in:
                case "passive":
                    idx = self.passive_queue.index(trackId, self.passive_index + 1)
                    self.passive_queue.pop(idx)
                    for e in self.queue_list:
                        if e["url"] == trackId and e["type"] == "passive":
                            self.queue_list.remove(e)
                            break
                    return True, None
                case "active":
                    idx = self.active_queue.index(trackId, self.active_index + 1)
                    self.active_queue.pop(idx)
                    for e in self.queue_list:
                        if e["url"] == trackId and e["type"] == "active":
                            self.queue_list.remove(e)
                            break
                    return True, None
        except ValueError:
            pass
        return False, "element not found"
