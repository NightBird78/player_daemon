import socket
import json
import os
import sys
import time


class MPV:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def _send_windows(self, cmd):
        for _ in range(10):
            try:
                with open(self.socket_path, "r+b", buffering=0) as pipe:
                    payload = (json.dumps(cmd) + "\n").encode()
                    pipe.write(payload)
                    response = pipe.readline().decode()
                    return json.loads(response)
            except FileNotFoundError:
                time.sleep(0.2)
                continue
            except Exception as e:
                print(f"Windows IPC Error: {e}")
                return None
        print("Не вдалося знайти пайп mpv після 10 спроб")
        return None

    def _send_unix(self, cmd):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(self.socket_path)
                s.sendall((json.dumps(cmd) + "\n").encode())
                response = s.recv(4096).decode()
                return json.loads(response)
        except Exception as e:
            print(f"Unix IPC Error: {e}")
            return None

    def send(self, cmd):
        if sys.platform == "win32":
            return self._send_windows(cmd)
        else:
            if not os.path.exists(self.socket_path):
                return None
            return self._send_unix(cmd)

    def get_property(self, prop):
        res = self.send({"command": ["get_property", prop]})
        return res.get("data") if res and "data" in res else None
