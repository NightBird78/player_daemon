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


@pytest.fixture
def windows_player(mocker):
    mock_popen = MagicMock()
    mock_popen.pid = 1234
    mocker.patch("base_player.subprocess.Popen", return_value=mock_popen)
    mocker.patch("base_player.cleanup_socket")

    p = SMTCPlayer(None)
    p.mpv = MagicMock()
    return p


@pytest.fixture
def linux_player(mocker):
    mock_popen = MagicMock()
    mock_popen.pid = 1234
    mocker.patch("base_player.subprocess.Popen", return_value=mock_popen)
    mocker.patch("base_player.cleanup_socket")

    p = MPRISPlayer()
    p.mpv = MagicMock()
    return p


@pytest.fixture
def mock_fetch():
    with patch("utils.fetch_metadata", new_callable=AsyncMock) as m:
        yield m


async def _test_play_current_success(player, mock_fetch):
    mock_fetch.return_value = {"title": "Test Song", "artist": ["Test Artist"]}
    player.active_queue = ["http://fakeurl.com"]
    player.active_index = 0
    player.mode = "active"

    await player.play_current()

    mock_fetch.assert_called_once_with("http://fakeurl.com")
    assert player.get_meta()["title"] == "Test Song"
    player.mpv.send.assert_called()


async def _test_websocket_actual_connection(player, aiohttp_client):
    app = web.Application()
    app["player"] = player
    app.router.add_get("/ws", server.websocket_handler)

    client = await aiohttp_client(app)

    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["type"] == "action"
        assert msg["action"] == "init"

        await ws.close()


async def _test_add_active_and_play(player, mock_fetch, aiohttp_client):
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


async def _test_async_next_fallback_to_passive(player, mock_fetch):
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


# ===== LINUX =====
@pytest.mark.asyncio
async def test_linux_play_current_success(linux_player, mock_fetch):
    await _test_play_current_success(linux_player, mock_fetch)


@pytest.mark.asyncio
async def test_linux_websocket_actual_connection(linux_player, aiohttp_client):
    await _test_websocket_actual_connection(linux_player, aiohttp_client)


@pytest.mark.asyncio
async def test_linux_add_active_and_play(linux_player, mock_fetch, aiohttp_client):
    await _test_add_active_and_play(linux_player, mock_fetch, aiohttp_client)


@pytest.mark.asyncio
async def test_linux_async_next_fallback_to_passive(linux_player, mock_fetch):
    await _test_async_next_fallback_to_passive(linux_player, mock_fetch)


# ==== WINDOWS ====
@pytest.mark.asyncio
async def test_windows_play_current_success(windows_player, mock_fetch):
    await _test_play_current_success(windows_player, mock_fetch)


@pytest.mark.asyncio
async def test_windows_websocket_actual_connection(windows_player, aiohttp_client):
    await _test_websocket_actual_connection(windows_player, aiohttp_client)


@pytest.mark.asyncio
async def test_windows_add_active_and_play(windows_player, mock_fetch, aiohttp_client):
    await _test_add_active_and_play(windows_player, mock_fetch, aiohttp_client)


@pytest.mark.asyncio
async def test_windows_async_next_fallback_to_passive(windows_player, mock_fetch):
    await _test_async_next_fallback_to_passive(windows_player, mock_fetch)
