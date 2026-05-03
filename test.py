from unittest.mock import AsyncMock, MagicMock, patch
import sys

mock_modules = [
    "pydbus",
    "pydbus.generic",
    "gbulb",
    "winsdk",
    "winsdk.windows.media",
    "winsdk.windows.media.playback",
]

for mod_name in mock_modules:
    sys.modules[mod_name] = MagicMock()


from gi.repository import GLib


def fake_variant(t, v):
    class Fake:
        def unpack(self):
            return v

        def __getitem__(self, key):  # якщо десь використовують як dict
            return v.get(key) if isinstance(v, dict) else None

    return Fake()


GLib.Variant = fake_variant


import pydbus.generic

pydbus.generic.signal = MagicMock()

from mpris_player import MPRISPlayer
from smtc_player import SMTCPlayer


import pytest
import asyncio
from aiohttp import web
import server


@pytest.fixture(params=["linux", "windows"], ids=["OS: Linux", "OS: Windows"])
def player(request, mocker):
    mock_popen = MagicMock(pid=1234)
    mocker.patch("base_player.subprocess.Popen", return_value=mock_popen)
    mocker.patch("base_player.cleanup_socket")
    match request.param:
        case "linux":
            p = MPRISPlayer()
        case "windows":
            p = SMTCPlayer(None)

        case _:
            raise OSError(f"can not test {request.param}")

    p.mpv = MagicMock()
    return p


@pytest.fixture
def mock_fetch():
    with patch("utils.fetch_metadata", new_callable=AsyncMock) as m:
        yield m


@pytest.mark.asyncio
async def test_play_current_success(player, mock_fetch):
    mock_fetch.return_value = {"title": "Test Song", "artist": ["Test Artist"]}
    player.active_queue = ["http://fakeurl.com"]
    player.active_index = 0
    player.mode = "active"

    await player.play_current()

    mock_fetch.assert_called_once_with("http://fakeurl.com")
    assert player.get_meta()["title"] == "Test Song"
    player.mpv.send.assert_called()


@pytest.mark.asyncio
async def test_websocket_actual_connection(player, aiohttp_client):
    app = web.Application()
    app["player"] = player
    app.router.add_get("/ws", server.websocket_handler)

    client = await aiohttp_client(app)

    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["type"] == "action"
        assert msg["action"] == "init"

        await ws.close()


@pytest.mark.asyncio
async def test_add_active_and_play(player, mock_fetch, aiohttp_client):
    mock_fetch.return_value = {"title": "Test Song", "artist": ["Test Artist"]}
    app = web.Application()
    app["player"] = player
    app.router.add_get("/ws", server.websocket_handler)

    client = await aiohttp_client(app)

    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["type"] == "action"
        assert msg["action"] == "init"

        await ws.send_json({"cmd": "play", "url": "http://fakeurl.com"})
        msg_resp = await ws.receive_json()
        assert msg_resp["type"] == "response"
        assert msg_resp["status"] == "Playing"
        await ws.send_json({"cmd": "play", "url": "http://fakeurl.com"})
        msg_resp = await ws.receive_json()
        msg_resp = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
        assert msg_resp["active_size"] == 2
        assert msg_resp["queue"] == [
            {
                "url": "http://fakeurl.com",
                "title": "Test Song",
                "artist": ["Test Artist"],
            }
        ]

        await ws.close()


@pytest.mark.asyncio
async def test_async_next_fallback_to_passive(player, mock_fetch):
    mock_fetch.return_value = {"title": "Next Song", "artist": ["Artist"]}

    player.active_queue = ["url1"]
    player.active_index = 0
    player.mode = "active"
    player.passive_queue = ["url2"]
    player.passive_index = -1

    await player.async_next()

    assert player.mode == "passive"
    assert player.passive_index == 0
    assert player.active_index == -1
    assert player.current_mode == "passive"


@pytest.mark.asyncio
async def test_async_next_with_step(player, mock_fetch):
    mock_fetch.return_value = {"title": "Next Song", "artist": ["Artist"]}

    player.passive_queue = ["url1", "url2", "url3", "url4", "url5", "url6"]
    player.passive_index = 1

    await player.async_next(count=2)

    assert player.mode == "passive"
    assert player.active_index == -1
    assert player.passive_index == 3
    assert player.current_mode == "passive"


@pytest.mark.asyncio
async def test_async_stop(player, mock_fetch):

    player.active_queue = ["url1", "url2"]
    player.active_index = 1
    player.passive_queue = ["url1", "url2", "url3", "url4", "url5", "url6"]
    player.passive_index = 3

    player.mode = "active"
    player.current_mode = "passive"

    player.PlaybackStatus = "Paused"

    await player.async_stop()

    assert player.PlaybackStatus == "Stopped"

    assert player.active_queue == []
    assert player.active_index == -1
    assert player.passive_queue == []
    assert player.passive_index == -1

    assert player.get_meta() == {"title": "wait for", "artist": ["queue"]}
