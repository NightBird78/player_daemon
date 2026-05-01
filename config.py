import os
import platform


SOCKET = "/tmp/mpv-ipc.sock"
PORT = 8765
IDENTITY = "YT Python Player"

match platform.system():
    case "Windows":
        SOCKET = r"\\.\pipe\mpv-ipc"
    case "Linux":
        SOCKET = "/tmp/mpv-ipc.sock"
    case _:
        raise TypeError("this OS doesn`t support")


def cleanup_socket():
    if os.path.exists(SOCKET):
        os.remove(SOCKET)
