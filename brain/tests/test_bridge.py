import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from modpack_brain.bridge import Bridge


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
