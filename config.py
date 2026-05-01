import os


MPRIS_SOCKET = r"\\.\pipe\mpv-ipc"
SMTC_SOCKET = "/tmp/mpv-ipc.sock"
LOCAL_DIR = "~/Music"
PORT = 8765
IDENTITY = "YT Python Player"


def cleanup_socket(socket):
    if os.path.exists(socket):
        os.remove(socket)
