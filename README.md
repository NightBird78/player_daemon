# Advanced WebSocket Player Daemon

Welcome to the **Advanced WebSocket Player Daemon**! This project allows you to control your music from any device with an internet connection using a web interface. For detailed information, please refer to the translations below.

- [English](readme/en/README.md)
- [Українська](readme/uk/README.md)

---

## Key Features

- **Two Priority Queues**:
  - **Active Queue**: Tracks to be listened to now
  - **Passive Queue**: Background music (automatically starts after Active Queue ends)
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

## Installation and Setup

For more detailed instructions on how to install, set up, and run the project, please refer to the translations below.

- [English](readme/en/README.md)
- [Українська](readme/uk/README.md)
