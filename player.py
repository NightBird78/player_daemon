import sys
import asyncio
from logger import setup_logger

log = setup_logger("player_creator")


def create_player():
    """
    Автоматично вибирає провайдера залежно від операційної системи.
    """

    match sys.platform:
        case "win32":
            log.info("detected NT")
            policy = asyncio.WindowsProactorEventLoopPolicy()
            loop = policy.new_event_loop()
            from smtc_player import SMTCPlayer

            return SMTCPlayer(loop), loop
        case "linux":
            if hasattr(sys, "getandroidapilevel"):
                log.info("detected android-like")
                return STANDALONEPlayer(), asyncio.new_event_loop()

            log.info("detected linux")
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
            log.info("Standalone mode")
            return STANDALONEPlayer(), asyncio.new_event_loop()
