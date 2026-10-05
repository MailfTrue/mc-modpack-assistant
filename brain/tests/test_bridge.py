import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from modpack_brain.bridge import Bridge, BridgeError


async def _start(events: list) -> Bridge:
    async def on_event(event: dict) -> None:
        events.append(event)

    bridge = Bridge("127.0.0.1", 0, lambda: "secret", on_event)
    await bridge.start()
    bridge.port = bridge._server.sockets[0].getsockname()[1]
    return bridge


async def test_event_delivered_with_valid_token():
    events: list = []
    bridge = await _start(events)
    try:
        url = f"ws://127.0.0.1:{bridge.port}"
        async with connect(url, additional_headers={"Authorization": "Bearer secret"}) as ws:
            await ws.send(json.dumps({"type": "hello", "mod_version": "test"}))
            await ws.send(json.dumps({"type": "event", "event": "join", "player": "Vasya"}))
            for _ in range(50):
                if events:
                    break
                await asyncio.sleep(0.02)
            assert bridge.connected
            assert await bridge.send({"type": "ping"})
            assert json.loads(await ws.recv()) == {"type": "ping"}
        assert events == [{"type": "event", "event": "join", "player": "Vasya"}]
    finally:
        await bridge.stop()


async def test_bad_token_rejected():
    bridge = await _start([])
    try:
        with pytest.raises(InvalidStatus):
            async with connect(f"ws://127.0.0.1:{bridge.port}", additional_headers={"Authorization": "Bearer nope"}):
                pass
        assert not bridge.connected
    finally:
        await bridge.stop()


async def test_request_response_and_ai_question():
    questions: list = []

    async def on_question(message: dict) -> None:
        questions.append(message)

    bridge = Bridge("127.0.0.1", 0, lambda: "secret", lambda e: asyncio.sleep(0), on_question)
    await bridge.start()
    port = bridge._server.sockets[0].getsockname()[1]
    try:
        async with connect(f"ws://127.0.0.1:{port}", additional_headers={"Authorization": "Bearer secret"}) as ws:
            for _ in range(50):
                if bridge.connected:
                    break
                await asyncio.sleep(0.02)
            pending = asyncio.create_task(bridge.request("online"))
            request = json.loads(await ws.recv())
            assert request["method"] == "online"
            await ws.send(json.dumps({"type": "response", "id": request["id"], "result": {"players": ["A"]}}))
            assert await pending == {"players": ["A"]}

            await ws.send(json.dumps({"type": "ai_question", "id": "q", "question": "?"}))
            for _ in range(50):
                if questions:
                    break
                await asyncio.sleep(0.02)
            assert questions[0]["id"] == "q"
    finally:
        await bridge.stop()


async def test_request_without_mod_fails():
    bridge = Bridge("127.0.0.1", 0, lambda: "secret", lambda e: asyncio.sleep(0))
    with pytest.raises(BridgeError):
        await bridge.request("online")
