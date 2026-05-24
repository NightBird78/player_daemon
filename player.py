import sys
import asyncio


def create_player():
    """
    Автоматично вибирає провайдера залежно від операційної системи.
    """

    match sys.platform:
        case "win32":
            loop = asyncio.new_event_loop()
            from smtc_player import SMTCPlayer

            return SMTCPlayer(loop), loop
        case "linux":
            import gbulb

            gbulb.install()
            from pydbus import SessionBus
            from mpris_player import MPRISPlayer

            player = MPRISPlayer()
            bus = SessionBus()
            bus.publish(
                "org.mpris.MediaPlayer2.python_player",
                ("/org/mpris/MediaPlayer2", player),
            )

            return player, asyncio.new_event_loop()
        case _:
            raise OSError(f"Платформа {sys.platform} не підтримується")
