import sys


def create_player(loop):
    """
    Автоматично вибирає провайдера залежно від операційної системи.
    """

    match sys.platform:
        case "win32":
            from smtc_player import SMTCPlayer

            return SMTCPlayer(loop)
        case "linux":
            import gbulb

            gbulb.install()
            from pydbus import SessionBus
            from mpris_player import MPRISPlayer

            player = MPRISPlayer()
            bus = SessionBus()
            bus.publish(
                "org.mpris.MediaPlayer2.MyPythonApp",
                ("/org/mpris/MediaPlayer2", player),
            )

            return player
        case _:
            raise OSError(f"Платформа {sys.platform} не підтримується")


# Приклад ініціалізації
# player = create_player()

# Якщо це Linux, реєструємо в DBus
# if sys.platform.startswith("linux"):
# from pydbus import SessionBus

# bus = SessionBus()
# bus.publish("org.mpris.MediaPlayer2.python_player", player)
