import json
import asyncio
import aiohttp
from aiohttp import web
from config import PORT
import utils

connected_clients = set()


async def ws_broadcast(data, _except=None):
    for ws in list(connected_clients):
        if _except and _except is ws:
            continue
        try:
            await ws.send_json(data)
        except:
            connected_clients.remove(ws)


async def send_data(ws, player, type, additional: dict = {}):
    meta = {k.split(":")[1]: v.unpack() for k, v in player.Metadata.items()}
    await ws.send_json(
        {
            "type": type,
            "mode": player.mode,
            "status": player.PlaybackStatus,
            "metadata": meta,
            "active_size": len(player.active_queue),
            "active_index": player.active_index,
            "passive_size": len(player.passive_queue),
            "passive_index": player.passive_index,
        }
        | additional
    )


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_clients.add(ws)

    player = request.app["player"]
    await send_data(ws, player, "action", {"action": "init"})

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            cmd = data.get("cmd")

            # ACTIVE playback
            if cmd == "play":
                player.add_active(data["url"])

            elif cmd == "active_playlist":
                items = utils.load_youtube_playlist(data["url"])
                player.set_active_queue(items)

            # PASSIVE queue
            elif cmd == "playlist":
                items = utils.load_youtube_playlist(data["url"])
                player.set_passive_queue(items)

            elif cmd == "add":
                player.add_passive(data["url"])

            # controls
            elif cmd == "control":
                if data["action"] == "next":
                    player.Next(ws_client=ws)

                elif data["action"] == "pause":
                    player.PlayPause(ws_client=ws)

                elif data["action"] == "stop":
                    player.Stop(ws_client=ws)

            await send_data(ws, player, "response")
    connected_clients.remove(ws)
    return ws


async def handle_index(request):
    try:
        # Відкриваємо файл у бінарному режимі
        with open("./index.html", "rb") as f:
            content = f.read()
        return web.Response(body=content, content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="Файл index.html не знайдено", status=404)


async def start_server(player):
    app = web.Application()
    app["player"] = player
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", websocket_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
