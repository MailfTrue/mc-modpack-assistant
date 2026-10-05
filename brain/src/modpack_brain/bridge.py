"""WebSocket-сервер для мода: мод подключается сюда и шлёт события сервера.

Протокол — JSON-объекты с полем `type`:
- мод → brain: `{"type": "hello", "mod_version": ...}`, `{"type": "event", "event": "join", ...}`
- brain → мод: зарезервировано для моста чата и команд (M4).
"""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

log = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class Bridge:
    def __init__(self, host: str, port: int, token: Callable[[], str | None], on_event: EventHandler) -> None:
        self.host = host
        self.port = port
        self._token = token
        self._on_event = on_event
        self._mod: ServerConnection | None = None
        self._server: Server | None = None

    @property
    def connected(self) -> bool:
        return self._mod is not None

    async def start(self) -> None:
        self._server = await serve(
            self._handle, self.host, self.port, process_request=self._authorize, ping_interval=20, ping_timeout=20
        )
        log.info("мост: слушаю ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def send(self, message: dict[str, Any]) -> bool:
        if self._mod is None:
            return False
        try:
            await self._mod.send(json.dumps(message, ensure_ascii=False))
            return True
        except ConnectionClosed:
            return False

    def _authorize(self, connection: ServerConnection, request: Request) -> Response | None:
        header = request.headers.get("Authorization", "")
        token = self._token()  # читаем каждый раз: мод создаёт токен при первом запуске сервера
        expected = f"Bearer {token}"
        if not token or not hmac.compare_digest(header.encode(), expected.encode()):
            log.warning("мост: отклонено подключение с неверным токеном от %s", connection.remote_address)
            return connection.respond(HTTPStatus.UNAUTHORIZED, "bad token\n")
        return None

    async def _handle(self, connection: ServerConnection) -> None:
        if self._mod is not None:
            log.info("мост: новое подключение мода, старое закрываю")
            await self._mod.close()
        self._mod = connection
        log.info("мост: мод подключился")
        try:
            async for raw in connection:
                try:
                    message = json.loads(raw)
                except ValueError:
                    log.warning("мост: не JSON: %r", raw[:200])
                    continue
                if not isinstance(message, dict):
                    continue
                await self._dispatch(message)
        except ConnectionClosed:
            pass
        finally:
            if self._mod is connection:
                self._mod = None
            log.info("мост: мод отключился")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "hello":
            log.info("мост: hello от мода %s", message.get("mod_version"))
        elif kind == "event":
            try:
                await self._on_event(message)
            except Exception:
                log.exception("мост: ошибка обработки события %s", message.get("event"))
        else:
            log.debug("мост: неизвестное сообщение %s", kind)
