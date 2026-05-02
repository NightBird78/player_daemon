import json
from mutagen.easyid3 import EasyID3
import asyncio
import os
import time


async def stream_links_async(url):
    """Асинхронно видає посилання з плейлиста по одному"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--no-warnings",
        "--lazy-playlist",
        "--quiet",
        "--print",
        "url",
        url,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        link = line.decode().strip()
        if link:
            yield link

    await process.wait()


cache = {}


async def fetch_metadata(url):
    """Повертає метадані асинхронно"""
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
        now = int(time.time())

        if url in cache:
            expired_keys = [k for k, v in cache.items() if now - v["time"] > 3600]
            for k in expired_keys:
                del cache[k]

            if url in cache:
                return cache[url]
        process = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-J",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        data = json.loads(stdout.decode())
        cache[url] = {
            "title": data.get("title"),
            "artist": [data.get("uploader", "Unknown")],
            "time": int(time.time()),
        }
        return cache[url]
