import json
import asyncio
import aiohttp
from aiohttp import web
from pathlib import Path
import mimetypes
from config import PORT, LOCAL_DIR
import utils

# ==================== ГЛОБАЛЬНІ ЗМІННІ ====================

connected_clients = set()
buckets = {}
DEBOUNCE_TIME = 0.5


# ==================== ДОПОМІЖНІ ФУНКЦІЇ ====================


async def ws_broadcast(data, exclude=None, only=None):
    """Розсилка повідомлення всім клієнтам"""
    if only:
        try:
            await only.send_json(data)
        except:
            connected_clients.discard(only)
        return

    clients = list(connected_clients)
    for ws in clients:
        if ws is exclude:
            await ws.send_json(data | {"type": "response"})
            continue
        try:
            await ws.send_json(data)
        except:
            connected_clients.discard(ws)


async def send_response(
    ws, player, message_type: str, additional: dict = None, update_queue: bool = False
):
    """Універсальна відправка відповіді"""
    await player.broadcast_state(
        None,
        type=message_type,
        additional=additional or {},
        update_queue=update_queue,
        _only=ws if message_type != "response" else None,
    )


# ==================== ОБРОБКА КОМАНД ====================


async def delayed_next(cmd: str, player, ws):
    """Debounce для кнопки Next"""
    try:
        await asyncio.sleep(DEBOUNCE_TIME)
        bucket = buckets.get(cmd)
        if bucket:
            await player.async_next(ws_client=ws, count=bucket["count"])
            buckets.pop(cmd, None)
    except asyncio.CancelledError:
        pass


async def process_local_files(player, ws):
    """Завантаження локальних аудіофайлів"""
    if not LOCAL_DIR:
        await send_response(
            ws, player, "warning", {"warning": "localdir is not defined"}
        )
        return

    try:
        path = Path(LOCAL_DIR)
        update = True

        for item in path.rglob("*"):
            if item.is_dir():
                continue

            mime_type, _ = mimetypes.guess_type(item)
            if not mime_type or not mime_type.startswith("audio/"):
                continue

            await player.add_passive(str(item.absolute()))

            if len(player.queue.passive_queue) % 200 == 0:
                await send_response(ws, player, "Loading", update_queue=update)
                update = False
            elif len(player.queue.passive_queue) % 10 == 0:
                await asyncio.sleep(0.05)

        await send_response(ws, player, "Loading", update_queue=update)

    except Exception as e:
        print(f"Помилка завантаження локальних файлів: {e}")


async def process_playlist(url: str, player, ws):
    """Завантаження плейлиста в фоні"""
    try:
        update = True
        async for item_url in utils.stream_links_async(url):
            await player.add_passive(item_url)
            if len(player.queue.passive_queue) % 200 == 0:
                await send_response(ws, player, "Loading", update_queue=update)
                update = False
            elif len(player.queue.passive_queue) % 10 == 0:
                await asyncio.sleep(0.05)

        await send_response(ws, player, "Loading", update_queue=update)
    except Exception as e:
        print(f"Помилка завантаження плейлиста: {e}")


# ==================== WEBSOCKET HANDLER ====================


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_clients.add(ws)

    player = request.app["player"]

    await send_response(ws, player, "action", {"action": "init"})

    async for msg in ws:
        if msg.type != aiohttp.WSMsgType.TEXT:
            continue

        try:
            data = json.loads(msg.data)
            cmd = data.get("cmd")
        except:
            continue

        update_queue = False

        # ==================== КОМАНДИ ====================

        if cmd == "play":
            success = await player.add_active(data["url"])
            update_queue = success
            if not success:
                await send_response(
                    ws,
                    player,
                    "warning",
                    {"warning": "cannot add playlist in active"},
                )
                continue

        elif cmd == "playlist":
            asyncio.create_task(process_playlist(data["url"], player, ws))

        elif cmd == "localplaylist":
            asyncio.create_task(process_local_files(player, ws))

        elif cmd == "add":
            await player.add_passive(data["url"])

        elif cmd == "control":
            action = data["action"]

            if action == "next":
                if cmd in buckets:
                    buckets[cmd]["task"].cancel()
                    buckets[cmd]["count"] += 1
                else:
                    buckets[cmd] = {"count": 1, "task": None}

                buckets[cmd]["task"] = asyncio.create_task(
                    delayed_next(cmd, player, ws)
                )
                continue

            elif action == "pause":
                await player.async_play_pause(ws_client=ws)
                continue
            elif action == "stop":
                await player.async_stop(ws_client=ws)
            elif action == "shuffle":
                await player.async_shuffle(ws_client=ws)

        elif cmd == "queue_action":
            action = data["action"]
            track_id = data["track_id"]
            queue_type = data.get("in")

            handlers = {
                "next": lambda: player.queue.next(track_id, queue_type),
                "move_up": lambda: player.queue.move(track_id, "up", queue_type),
                "move_down": lambda: player.queue.move(track_id, "down", queue_type),
                "to_active": lambda: player.queue.change(track_id, "active"),
                "to_passive": lambda: player.queue.change(track_id, "passive"),
                "postpone": lambda: player.queue.postpone(track_id, queue_type),
                "remove": lambda: player.queue.remove(track_id, queue_type),
            }

            if action in handlers:
                status, response = handlers[action]()
                update_queue = status
                if not status:
                    await send_response(ws, player, "warning", {"warning": response})
                    continue

        elif cmd == "search":
            result = await utils.search(data["text"])
            await send_response(ws, player, "search_result", {"search_result": result})
            continue

        await send_response(
            ws,
            player,
            "response",
            additional={"action": data.get("action")} if cmd == "control" else {},
            update_queue=update_queue,
        )

    connected_clients.discard(ws)
    return ws


# ==================== HTTP ====================


async def handle_index(request):
    try:
        with open("./index.html", "rb") as f:
            return web.Response(body=f.read(), content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="index.html not found", status=404)


# ==================== ЗАПУСК СЕРВЕРА ====================


async def start_server(player):
    app = web.Application()
    app["player"] = player

    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", websocket_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"Сервер запущено на порту {PORT}")
