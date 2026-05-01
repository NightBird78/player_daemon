import asyncio

# import gbulb
# from pydbus import SessionBus

# from player_core import Player
from server import start_server, ws_broadcast
from player import create_player

# gbulb.install()


async def poll_proc(player):
    while True:
        await asyncio.sleep(5)
        if not player.proc:
            continue
        if player.proc.poll() is None:
            await ws_broadcast(
                {
                    "type": "process",
                    "percent": player.mpv.get_property("percent-pos"),
                }
            )
            continue
        player.proc = None
        if player.PlaybackStatus == "Stopped":
            continue

        player.Next()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    player = create_player(loop)

    loop.create_task(start_server(player))
    loop.create_task(poll_proc(player))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
