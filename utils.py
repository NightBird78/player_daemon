import subprocess
import json
from mutagen.easyid3 import EasyID3


def load_youtube_playlist(url):
    output = subprocess.check_output(
        ["yt-dlp", "--flat-playlist", "-J", url], text=True
    )
    data = json.loads(output)
    return [
        f"https://www.youtube.com/watch?v={e['id']}"
        for e in data.get("entries", [])
        if e.get("id")
    ]


def fetch_metadata(url):
    """Повертає словник з метаданими залежно від типу файлу"""
    if url.endswith(".mp3"):
        try:
            audio = EasyID3(url)
            return {
                "title": audio.get("title", ["Невідомо"])[0],
                "artist": [audio.get("artist", ["Невідомо"])[0]],
            }
        except:
            return {"title": "Unknown File", "artist": ["Unknown"]}
    else:
        output = subprocess.check_output(["yt-dlp", "-J", url], text=True)
        data = json.loads(output)
        return {"title": data["title"], "artist": [data["uploader"]]}
