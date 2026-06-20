import sys
import asyncio
import pytest
from hypothesis import given, strategies as st
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web

from queue_manager import QueueManager

# --- Системні моки (повинні бути до імпорту локальних модулів) ---
mock_modules = [
    "gi",
    "gi.repository",
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

GLib.Variant = lambda t, v: MagicMock(unpack=lambda: v)

import server
from mpris_player import MPRISPlayer
from smtc_player import SMTCPlayer

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# --- Допоміжні класи ---


class WSMessageManager:
    def __init__(self, ws):
        self.ws = ws
        self.messages = []
        self._stop = False

    async def listen(self):
        async for msg in self.ws:
            if self._stop:
                break
            data = msg.json()
            self.messages.append(data)

    async def wait_for_type(self, msg_type, timeout=2.0):
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            for i, msg in enumerate(self.messages):
                if msg.get("type") == msg_type:
                    return self.messages.pop(i)
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Таймаут очікування повідомлення типу {msg_type}")


# --- Фікстури ---


@pytest.fixture(params=["linux", "windows"], ids=["OS: Linux", "OS: Windows"])
def player(request, mocker):
    mocker.patch("base_player.subprocess.Popen", return_value=MagicMock(pid=1234))
    mocker.patch("base_player.cleanup_socket")

    p = MPRISPlayer() if request.param == "linux" else SMTCPlayer(None)
    p.mpv = MagicMock()
    p.mpv.send = AsyncMock(return_value={"error": "success"})
    p.mpv.event_queue.get = AsyncMock(return_value={"type": "file_loaded"})
    p.init_mpv = AsyncMock()
    return p


@pytest.fixture(autouse=True)
def mock_fetch():
    with patch("utils.fetch_metadata", new_callable=AsyncMock) as m:
        m.return_value = {"title": "Test Song", "artist": ["Test Artist"]}
        yield m


@pytest.fixture(autouse=True)
def mock_playlist():
    with patch("utils.is_playlist", new_callable=AsyncMock) as m:
        m.return_value = False
        yield m


@pytest.fixture
def mock_shuffle():
    with patch("random.shuffle") as m:

        def set_result(shuffled_list):
            def side_effect(input_list):
                input_list[:] = shuffled_list

            m.side_effect = side_effect

        m.set_result = set_result
        yield m


@pytest_asyncio.fixture
async def ws_manager(player, aiohttp_client):
    app = web.Application()
    app["player"] = player
    app.router.add_get("/ws", server.websocket_handler)
    client = await aiohttp_client(app)

    async with client.ws_connect("/ws") as ws:
        manager = WSMessageManager(ws)
        task = asyncio.create_task(manager.listen())

        await manager.wait_for_type("action")

        yield manager

        manager._stop = True
        task.cancel()


# --- Тести логіки плеєра (Unit) ---


@pytest.mark.asyncio
async def test_player_play_current_updates_metadata(player):
    player.queue.active_queue = ["http://fakeurl.com"]
    player.queue.active_index = 0
    player.queue.mode = "active"

    await player.play_current()

    meta = player.get_meta()
    assert meta == {"title": "Test Song", "artist": ["Test Artist"]}


@pytest.mark.asyncio
async def test_player_pause(player):
    player.queue.active_queue = ["http://fakeurl.com"]
    player.queue.active_index = 0
    player.queue.mode = "active"
    player.PlaybackStatus = "Playing"

    await player.async_play_pause()

    assert player.PlaybackStatus == "Paused"
    player.mpv.send.assert_called()

    await player.async_play_pause()

    assert player.PlaybackStatus == "Playing"
    player.mpv.send.assert_called()


@pytest.mark.asyncio
async def test_ws_playpause(player, ws_manager):

    player.queue.active_queue = ["http://fakeurl.com"]
    player.queue.active_index = 0
    player.queue.mode = "active"
    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "control", "action": "pause"})

    resp = await ws_manager.wait_for_type("response")
    assert resp["type"] == "response"
    assert resp["status"] == "Paused"

    await ws_manager.ws.send_json({"cmd": "control", "action": "pause"})

    resp = await ws_manager.wait_for_type("response")
    assert resp["type"] == "response"
    assert resp["status"] == "Playing"


@pytest.mark.asyncio
async def test_player_stop_clears_everything(player):
    player.queue.active_queue = ["url1"]
    player.queue.active_index = 0
    player.PlaybackStatus = "Playing"

    await player.async_stop()

    assert player.queue.active_queue == []
    assert player.queue.active_index == -1
    assert player.PlaybackStatus == "Stopped"


@pytest.mark.asyncio
async def test_fallback_to_passive_when_active_ends(player):
    player.queue.active_queue = ["last_active_url"]
    player.queue.active_index = 0
    player.queue.mode = "active"
    player.queue.passive_queue = ["passive_url"]
    player.queue.passive_index = -1

    await player.async_next()

    assert player.queue.mode == "passive"
    assert player.queue.passive_index == 0


# --- Тести WebSocket API (Integration) ---


@pytest.mark.asyncio
async def test_ws_init_connection(player, aiohttp_client):
    app = web.Application()
    app["player"] = player
    app.router.add_get("/ws", server.websocket_handler)
    client = await aiohttp_client(app)

    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["action"] == "init"


@pytest.mark.asyncio
async def test_ws_command_play_updates_status(ws_manager):
    url = "http://fakeurl.com"

    await ws_manager.ws.send_json({"cmd": "play", "url": url})
    resp = await ws_manager.wait_for_type("response")
    assert resp["type"] == "response"
    assert resp["status"] == "Playing"


@pytest.mark.asyncio
async def test_ws_multiple_plays_queue_management(player, ws_manager):
    url = "http://fakeurl.com"
    player.queue.passive_queue = ["url"]
    player.queue.passive_index = 0
    player.queue.mode = "active"
    player.queue.current_mode = "passive"
    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "play", "url": url})

    resp = await ws_manager.wait_for_type("response")
    loading = await ws_manager.wait_for_type("update")

    assert resp["status"] == "Playing"
    assert resp["active_size"] == 1
    assert resp["passive_size"] == 1
    assert loading["active_size"] == 1
    assert loading["passive_size"] == 1
    assert loading["queue"][0]["url"] == url


@pytest.mark.asyncio
async def test_ws_play_next(player, ws_manager):
    player.queue.active_queue = ["url1", "url2"]
    player.queue.active_index = 0
    player.queue.mode = "active"
    player.queue.current_mode = "active"
    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "control", "action": "next"})

    resp = await ws_manager.wait_for_type("response")

    assert resp["status"] == "Playing"
    assert resp["active_index"] == 1


@pytest.mark.asyncio
async def test_ws_eoq(player, ws_manager):
    player.queue.passive_queue = ["passive_url"]
    player.queue.passive_index = 0
    player.queue.mode = "passive"
    player.PlaybackStatus = "Playing"

    await player.async_next()

    resp = await ws_manager.wait_for_type("action")

    assert resp["action"] == "Stop/End"
    assert resp["status"] == "Stopped"


@pytest.mark.asyncio
async def test_ws_queue_structure(player, ws_manager):
    expected = {
        "url2": "active",
        "url3": "active",
        "url4": "passive",
        "url5": "passive",
        "url6": "passive",
    }

    player.queue.active_queue = ["url1", "url2", "url3"]
    player.queue.passive_queue = ["url4", "url5", "url6"]

    player.queue.active_index = 0
    player.queue.passive_index = -1

    player.queue.mode = "active"
    player.PlaybackStatus = "Playing"

    await player._update_queue()

    resp_loading = await ws_manager.wait_for_type("update")

    assert len(resp_loading["queue"]) == 5
    actual = {}
    for i in resp_loading["queue"]:
        actual[i["url"]] = i["type"]

    assert actual == expected


@pytest.mark.asyncio
async def test_ws_shuffle_passive(mock_shuffle, player, ws_manager):
    expected_result = ["url3", "url1", "url2"]
    mock_shuffle.set_result(expected_result)

    player.queue.passive_queue = ["url1", "url2", "url3"]
    player.queue.passive_index = 1

    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "control", "action": "shuffle"})

    response = await ws_manager.wait_for_type("response")
    resp_loading_1 = await ws_manager.wait_for_type("update")
    resp_loading_2 = await ws_manager.wait_for_type("update")

    assert response["passive_index"] == 0
    assert len(resp_loading_1["queue"]) == 0
    assert len(resp_loading_2["queue"]) == 2

    assert list(player.queue.passive_queue) == expected_result

    mock_shuffle.assert_called_once()


@pytest.mark.asyncio
async def test_ws_shuffle_passive_while_active(mock_shuffle, player, ws_manager):
    expected_result = ["url3", "url1", "url2"]
    mock_shuffle.set_result(expected_result)

    player.queue.passive_queue = ["url1", "url2", "url3"]
    player.queue.passive_index = 1
    player.queue.active_queue = ["url0"]
    player.queue.active_index = 0
    player.queue.mode = "active"
    player.queue.current_mode = "active"

    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "control", "action": "shuffle"})

    response = await ws_manager.wait_for_type("response")
    resp_loading = await ws_manager.wait_for_type("update")

    assert response["passive_index"] == -1
    assert len(resp_loading["queue"]) == 3

    assert list(player.queue.passive_queue) == expected_result

    mock_shuffle.assert_called_once()


@pytest.mark.asyncio
async def test_ws_shuffle_passive_switch_active(mock_shuffle, player, ws_manager):
    expected_result = ["url3", "url1", "url2"]
    mock_shuffle.set_result(expected_result)

    player.queue.passive_queue = ["url1", "url2", "url3"]
    player.queue.passive_index = 1
    player.queue.active_queue = ["url0"]
    player.queue.active_index = -1
    player.queue.mode = "active"
    player.queue.current_mode = "passive"

    player.PlaybackStatus = "Playing"

    await ws_manager.ws.send_json({"cmd": "control", "action": "shuffle"})

    response = await ws_manager.wait_for_type("response")
    resp_loading_1 = await ws_manager.wait_for_type("update")
    resp_loading_2 = await ws_manager.wait_for_type("update")

    print(player.queue.passive_queue)

    assert response["passive_index"] == -1
    assert response["active_index"] == 0
    assert len(resp_loading_1["queue"]) == 0
    assert len(resp_loading_2["queue"]) == 3

    assert list(player.queue.passive_queue) == expected_result

    mock_shuffle.assert_called_once()


# ===== test queue actions =====
unique_tracks_strategy = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=5),
    min_size=1,
    max_size=7,
    unique=True,
)


@given(
    tracks=unique_tracks_strategy,
    direction=st.sampled_from(["up", "down"]),
    target_pos=st.integers(min_value=0, max_value=20),
)
def test_hypothesis_move_action(tracks, direction, target_pos):
    qm = QueueManager()
    qm.active_queue = tracks.copy()

    if target_pos >= len(tracks):
        target_pos = len(tracks) - 1

    target_track = tracks[target_pos]

    qm.active_index = -1

    res, cause = qm.move(target_track, _to=direction, _in="active")

    if direction == "up" and target_pos == 0:
        assert res is False
        assert cause == "Element is already at the top"
        assert qm.active_queue == tracks

    elif direction == "down" and target_pos == len(tracks) - 1:
        assert res is False
        assert cause == "Element is already at the bottom"
        assert qm.active_queue == tracks

    else:
        assert res is True
        assert cause is None

        assert len(qm.active_queue) == len(tracks)
        assert set(qm.active_queue) == set(tracks)

        new_pos = qm.active_queue.index(target_track)

        if direction == "up":
            assert new_pos == target_pos - 1
            assert qm.active_queue[target_pos] == tracks[target_pos - 1]

        elif direction == "down":
            assert new_pos == target_pos + 1
            assert qm.active_queue[target_pos] == tracks[target_pos + 1]


@given(tracks=unique_tracks_strategy)
def test_move_track_not_found(tracks):
    qm = QueueManager()
    qm.active_queue = tracks.copy()
    qm.active_index = -1

    fake_track = "NOT_EXIST"

    res, cause = qm.move(fake_track, _to="up", _in="active")

    assert res is False
    assert cause == "no this element in active"
    assert qm.active_queue == tracks
