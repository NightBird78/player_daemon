import asyncio
import json
import sys
import time


class MPVError(Exception):
    pass


class MPV:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.reader = None
        self.writer = None
        self.pending_requests = {}
        self.reader_task = None
        self.event_queue = asyncio.Queue()

    async def connect(self):
        """Асинхронне підключення."""
        if sys.platform == "win32":
            self.reader, self.writer = await asyncio.open_connection(
                pipe=self.socket_path
            )
        else:
            self.reader, self.writer = await asyncio.open_unix_connection(
                self.socket_path
            )
        self.reader_task = asyncio.create_task(self._reader_loop())

        await self.send({"command": ["observe_property", 1, "percent-pos"]})

    async def _reader_loop(self):
        try:
            while True:
                line_bytes = await self.reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    response = json.loads(line)
                    req_id = response.get("request_id")
                    if req_id in self.pending_requests:
                        self.pending_requests[req_id].set_result(response)

                    elif (
                        response.get("event") == "property-change"
                        and response.get("name") == "percent-pos"
                    ):
                        percent_val = response.get("data")
                        if percent_val is not None:
                            await self.event_queue.put(
                                {"type": "percent_changed", "value": percent_val}
                            )

                    elif response.get("event") == "end-file":
                        if response.get("reason") == "eof":
                            await self.event_queue.put({"type": "track_ended"})

                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Reader Error: {e}")

    async def send(self, cmd):
        """Абсолютно безпечний асинхронний виклик."""
        try:
            if not self.writer:
                print("writer is none")
                await self.connect()

            req_id = int(time.time() * 1000000)
            cmd["request_id"] = req_id

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self.pending_requests[req_id] = future

            try:
                payload = (json.dumps(cmd) + "\n").encode("utf-8")
                self.writer.write(payload)
                await self.writer.drain()

                return await future
            except Exception as e:
                print(f"Async Send Error: {e}")
                return None
            finally:
                self.pending_requests.pop(req_id, None)
        except Exception as e:
            print("error in send", e)

    async def get_property(self, prop):
        res = await self.send({"command": ["get_property", prop]})
        return res.get("data") if res and "data" in res else None
