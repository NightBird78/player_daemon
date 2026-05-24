from server import start_server, ws_broadcast
from player import create_player


async def event_processor(player):
    print("Event-driven процесор MPV запущено.")
    last_percent = -1

    while True:
        event = await player.mpv.event_queue.get()

        if not player.proc:
            continue

        if event["type"] == "percent_changed":
            current_percent = int(event["value"])

            if current_percent != last_percent:
                last_percent = current_percent
                await ws_broadcast(
                    {
                        "type": "process",
                        "percent": current_percent,
                    }
                )

        elif event["type"] == "track_ended":
            if player.PlaybackStatus == "Stopped":
                continue
            await player.async_next()


if __name__ == "__main__":
    player, loop = create_player()

    loop.create_task(start_server(player))
    loop.create_task(event_processor(player))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
