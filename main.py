import asyncio

from server import start_server, ws_broadcast
from player import create_player


async def poll_proc(player):
    while True:
        await asyncio.sleep(5)
        if not player.proc:
            continue
        if player.proc.poll() is None:
            res = player.mpv.get_property("percent-pos")
            await ws_broadcast(
                {
                    "type": "process",
                    "percent": res,
                }
            )
            continue
        player.proc = None
        if player.PlaybackStatus == "Stopped":
            continue

        await player.async_next()


if __name__ == "__main__":
    player, loop = create_player()

    loop.create_task(start_server(player))
    loop.create_task(poll_proc(player))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
