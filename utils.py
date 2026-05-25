import json
from mutagen.easyid3 import EasyID3
import asyncio
import os
import time
from yt_dlp import YoutubeDL
import subprocess
import concurrent.futures


async def search(text):
    """шукає перші 5 результатів за текстом та повертає дані разом із прев'ю"""

    ydl_opts = {
        "format": "bestaudio/best",
        "extract_flat": True,
        "quiet": True,
    }

    def find():
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch5:{text}", download=False)

                if not info or "entries" not in info:
                    return []

                results = []
                for entry in info["entries"]:
                    thumbnail = entry.get("thumbnail")
                    if not thumbnail and entry.get("thumbnails"):
                        thumbnail = entry["thumbnails"][-1].get("url")

                    results.append(
                        {
                            "title": entry.get("title"),
                            "url": entry.get("url")
                            if entry.get("url")
                            else f"https://www.youtube.com/watch?v={entry.get('id')}",
                            "duration": entry.get("duration"),
                            "thumbnail": thumbnail,
                        }
                    )

                return results

            except Exception as e:
                print(f"Помилка пошуку: {e}")
                return []

    return await asyncio.to_thread(find)


async def is_playlist(url):
    """Перевіряє, чи є посилання плейлистом, без важких операцій"""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
        "simulate": True,
    }

    def check():
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return (
                    info.get("_type") == "playlist"
                    or "entries" in info
                    or "playlist?list=" in info.get("url")
                )
            except Exception:
                return False

    return await asyncio.to_thread(check)


def sync_worker(url, queue, loop):
    """
    Працює в окремому потоці. Потоково читає stdout yt-dlp
    і безпечно перекидає рядки в асинхронну чергу.
    """
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

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env
    )

    for line in process.stdout:
        link = line.strip()
        if link == "NA":
            loop.call_soon_threadsafe(queue.put_nowait, url)
            break
        if link:
            loop.call_soon_threadsafe(queue.put_nowait, link)

    process.wait()
    loop.call_soon_threadsafe(queue.put_nowait, None)


async def stream_links_async(url):
    """
    Справжній асинхронний генератор.
    Видає лінки одразу, як тільки yt-dlp виплюне їх у stdout.
    """
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, sync_worker, url, queue, loop)

    try:
        while True:
            link = await queue.get()

            if link is None:
                break

            yield link
    finally:
        executor.shutdown(wait=False)


cache = {}


async def fetch_metadata(url):
    """Повертає метадані асинхронно"""
    if url.endswith(".mp3"):
        try:
            audio = EasyID3(url)
            return {
                "title": audio.get("title", ["Невідомо"])[0],
                "artist": audio.get("artist", ["Невідомо"])[0],
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
                u = cache[url]
                return {"title": u["title"], "artist": u["artist"]}
        process = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-J",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        data = json.loads(stdout.decode())
        if data is None:
            return None
        cache[url] = {
            "title": data.get("title"),
            "artist": data.get("uploader", "Unknown"),
            "time": int(time.time()),
        }
        u = cache[url]
        return {"title": u["title"], "artist": u["artist"]}
