import os


MPRIS_SOCKET = "/tmp/mpv-ipc.sock"
SMTC_SOCKET = r"\\.\pipe\mpv-ipc"
LOCAL_DIR = "~/Music"
PORT = 8765
IDENTITY = "YT Python Player"


def cleanup_socket(socket):
    if os.path.exists(socket):
        os.remove(socket)
