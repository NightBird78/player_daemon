import socket
import json
import os


class MPV:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def send(self, cmd):
        if not os.path.exists(self.socket_path):
            return None
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(self.socket_path)
                s.send((json.dumps(cmd) + "\n").encode())
                response = s.recv(4096).decode()
                return json.loads(response)
        except Exception as e:
            print(f"IPC error: {e}")
            return None

    def get_property(self, prop):
        res = self.send({"command": ["get_property", prop]})
        return res.get("data") if res and "data" in res else None
