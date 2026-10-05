"""WebSocket-сервер для мода: мод подключается сюда, шлёт события и вопросы `/ai`, получает сообщения и ответы.

Протокол — JSON-объекты с полем `type`:
- мод → brain: `hello`, `event` (join, death, …), `ai_question` (вопрос из игры), `response` (ответ на `request`)
- brain → мод: `chat` (сообщение из Telegram), `ai_answer`, `request` (например, `{"method": "online"}`)
"""

from __future__ import annotations

import asyncio
import hmac
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class BridgeError(Exception):
    """Мод не подключён, не ответил вовремя или вернул ошибку."""


class Bridge:
    def __init__(
        self,
        host: str,
        port: int,
        token: Callable[[], str | None],
        on_event: Handler,
        on_ai_question: Handler | None = None,
        on_data_exported: Handler | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._token = token
        self._on_event = on_event
        self._on_ai_question = on_ai_question
        self._on_data_exported = on_data_exported
        self._mod: ServerConnection | None = None
        self._server: Server | None = None
        self._ids = itertools.count(1)
        self._requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

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

    async def request(self, method: str, timeout: float = 5.0, **params: Any) -> dict[str, Any]:
        """Запрос к моду с ответом (например, список игроков онлайн)."""
        request_id = next(self._ids)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._requests[request_id] = future
        try:
            if not await self.send({"type": "request", "id": request_id, "method": method, **params}):
                raise BridgeError("сервер не подключён")
            try:
                response = await asyncio.wait_for(future, timeout)
            except TimeoutError as error:
                raise BridgeError("сервер не ответил") from error
        finally:
            self._requests.pop(request_id, None)
        if "error" in response:
            raise BridgeError(str(response["error"]))
        return response.get("result") or {}

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
                if isinstance(message, dict):
                    await self._dispatch(message)
        except ConnectionClosed:
            pass
        finally:
            if self._mod is connection:
                self._mod = None
                for future in self._requests.values():
                    if not future.done():
                        future.set_exception(BridgeError("сервер отключился"))
            log.info("мост: мод отключился")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "hello":
            log.info("мост: hello от мода %s", message.get("mod_version"))
        elif kind == "event":
            await self._safe(self._on_event, message)
        elif kind == "response":
            future = self._requests.get(message.get("id"))  # type: ignore[arg-type]
            if future is not None and not future.done():
                future.set_result(message)
        elif kind == "data_exported" and self._on_data_exported is not None:
            task = asyncio.create_task(self._safe(self._on_data_exported, message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif kind == "ai_question" and self._on_ai_question is not None:
            # Ответ ИИ идёт долго — не держим цикл чтения сообщений.
            task = asyncio.create_task(self._safe(self._on_ai_question, message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            log.debug("мост: неизвестное сообщение %s", kind)

    @staticmethod
    async def _safe(handler: Handler, message: dict[str, Any]) -> None:
        try:
            await handler(message)
        except Exception:
            log.exception("мост: ошибка обработки %s", message.get("event") or message.get("type"))
