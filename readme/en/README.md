# Advanced WebSocket Player Daemon

**Advanced WebSocket Player Daemon** is a modern remote audio player for Linux and Windows with support for YouTube and local files.

Control your music from any device - phone, tablet, another PC, or even a browser on the fridge - through a convenient web interface.
<p align="center">
  <img alt="desctop-view" src="https://github.com/user-attachments/assets/caca69e4-8497-4801-941d-69bd8131ba0b" height="400" />
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img alt="mobile-view" src="https://github.com/user-attachments/assets/d00a8241-ce22-4320-b50f-18db18fc098d" height="400" />
</p>

---

## Main Idea

Just "order" a song from your computer without getting up.  

**Adv WS Player** is a lightweight, fast, and reliable daemon that allows you to add tracks to the queue and control playback in real-time via WebSocket.

---

## Key Features

- **Two Priority Queues**:
  - **Active Queue**: Tracks to be listened to now
  - **Passive Queue**: Background music (automatically starts after Active)
- Support for **YouTube** (links and playlists) via `yt-dlp`
- Support for **local MP3 files** with ID3 tag reading
- **WebSocket** control in real-time
- **MPRIS** (Linux) and **SMTC** (Windows) integration with system media keys, KDE Connect, GNOME, etc.
- User-friendly web interface with progress bar and logs
- Automatic transition from Active Queue to Passive Queue

---

## Technology Stack

- **Backend**: Python 3 + asyncio + websockets
- **Player**: [mpv](https://mpv.io/) (via Unix socket / IPC)
- **YouTube**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Metadata**: `mutagen`
- **MPRIS (Linux)**: `pydbus` + GLib
- **Frontend**: Pure HTML + CSS + JavaScript (single-page application)

---

## Installation, Setup, and Configuration

For detailed instructions on how to install, set up, and run the project, please refer to the following sections:

### 1. Creating a Virtual Environment (Recommended for All OS)

```bash
# Create venv
python3 -m venv venv

# Activate (Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate
```

### 2. Installation for Linux (Ubuntu / Debian)

Run all commands in the terminal.

#### 2.1. System Dependencies
```bash
sudo apt update && sudo apt install -y \
    mpv \
    python3-pip \
    python3-dbus \
    python3-gi \
    gir1.2-glib-2.0
```

#### 2.2. Python Libraries
```bash
pip install websockets pydbus mutagen gbulb yt-dlp aiohttp pygobject==3.48.2
```

### 3. Installation for Windows

#### 3.1. Download Required Programs
1. Download **mpv** from [the official website](https://mpv.io/).
2. Download **FFmpeg** (includes `ffmpeg.exe` and `ffprobe.exe`) from [the official website](https://ffmpeg.org/).

#### 3.2. File Placement
Extract the following files from the downloaded archives and **copy them directly into the root directory of the project** (alongside `README.md` and `main.py`):

- `mpv.com`
- `ffmpeg.exe`
- `ffprobe.exe`

#### 3.3. Python Libraries
Open a **Command Prompt**/**cmd** or **PowerShell** in the project directory and run:
```bash
pip install websockets mutagen yt-dlp aiohttp winsdk
```

### 4. Updating Components

If video or audio stops working (often due to an outdated `yt-dlp`):

```bash
pip install -U yt-dlp
```

### 5. Running the Project

1. **Clone the repository** (if you haven't already):
   ```bash
   git clone https://github.com/NightBird78/player_daemon.git
   cd player_daemon
   ```

2. **Activate the virtual environment** (if using venv).

3. **Start the server**:
   ```bash
   python main.py
   ```

The server will be accessible at: **http://localhost:8765**, and you will also receive an IP address like `192.168.x.x:8765` for connecting from other devices.

4. Open this URL in a browser on any device in the same local network.

### 6. Autostart (Linux - systemd)

Create a user service file:

```bash
mkdir -p ~/.config/systemd/user/
nano ~/.config/systemd/user/adv-ws-player.service
```

Insert the following content into the file:

```ini
[Unit]
Description=Advanced WebSocket Player
After=network-online.target pipewire.service pulseaudio.service
Wants=network-online.target

[Service]
Type=simple

WorkingDirectory=/path/to/project
Environment="PATH=/path/to/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/path/to/venv/bin/python /path/to/your/project/main.py

Restart=always

[Install]
WantedBy=default.target
```

Replace `/path/to/project` with the actual path.

### Activate Autostart
```bash
systemctl --user daemon-reload
systemctl --user enable --now adv-ws-player.service
```

---

**Done!** After completing these steps, the project should start. If you encounter any issues — check if all files (`mpv.com`, `ffmpeg.exe`) are located in the root directory of the project and if the virtual environment is activated.
---

## How to Use

### Adding Tracks

- **Play**: Insert a YouTube link or path to an `.mp3` file
- **Playlist**: Insert a YouTube playlist link (will be added to Passive Queue)

### Control

- Buttons in the web interface: Play/Pause, Next, Stop, Shuffle
- System media keys and programs (KDE Connect, polybar, media keys, etc.)

### Logs

- **Actions Log**: Commands received from other clients
- **Response Log**: Server responses and state changes

Logs help understand what is happening, especially when working with multiple devices/clients.

---

## Architecture

- `Active Queue` has higher priority
- After all tracks in the Active Queue are finished, playback automatically starts from the Passive Queue
- Asynchronous architecture on asyncio
- Clear separation of queue logic, player, and web interface

---

## Roadmap

- [x] Full list and editing of queues in the web interface
- [ ] Autocompletion of Passive Queue (by genre, mood, recommendations)
- [ ] Synchronization between multiple clients
- [ ] Improved error handling and retry mechanisms

---

## Why It Was Done This Way?

The project was created for maximum **convenience** in daily use and understanding of the architecture. Most components are implemented manually to have full control and minimal dependencies.

---

## Author

Created with love for home automation and quality music.

**Feedback, ideas, and pull requests** - very welcome!

---
