from base_player import BasePlayer
from config import STANDALONE_SOCKET


class StandalonePlayer(BasePlayer):
    def __init__(self):
        super().__init__(STANDALONE_SOCKET)

    def get_meta(self):
        return self.Metadata

    def set_meta(self, title, artist):
        if not isinstance(artist, list):
            artist = [artist]
        self.Metadata = {"title": title, "artist": artist}

    def update_widget(self, **kw):
        pass
