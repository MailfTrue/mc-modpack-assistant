"""Закреплённое сообщение со статусом сервера: одно на чат, бот его редактирует, а не пишет заново."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..bridge import Bridge, BridgeError

log = logging.getLogger(__name__)

# id закреплённого сообщения переживает перезапуски — иначе каждый старт сервера плодил бы новое.
STATE_FILE = Path("modpack-bridge") / "status-message.json"
# Сверка со списком игроков на сервере — на случай пропущенных событий.
REFRESH_SECONDS = 5 * 60
FIRST_REFRESH_SECONDS = 15
# Вход/выход: игрок попадает в список (и пропадает из него) чуть позже события.
EVENT_DELAY_SECONDS = 2.0


@dataclass
class ServerState:
    phase: str = "starting"  # starting | online | offline
    players: list[str] = field(default_factory=list)
    max_players: int | None = None


def render(state: ServerState, *, pack: str = "", address: str = "") -> str:
    if state.phase == "online":
        lines = ["🟢 <b>Сервер онлайн</b>"]
        count = f"{len(state.players)}/{state.max_players}" if state.max_players else str(len(state.players))
        names = ", ".join(escape(p) for p in sorted(state.players, key=str.lower))
        lines.append(f"👥 Игроки {count}" + (f": {names}" if names else " — никого"))
    elif state.phase == "starting":
        lines = ["🟡 <b>Сервер запускается…</b>"]
    else:
        lines = ["🔴 <b>Сервер выключен</b>"]
    if address:
        lines.append(f"🌐 Адрес: <code>{escape(address)}</code>")
    if pack:
        lines.append(f"🧩 {escape(pack)}")
    return "\n".join(lines)


def keyboard(panel_url: str) -> InlineKeyboardMarkup | None:
    if not panel_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть панель", url=panel_url)]])


class StatusBoard:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        server_dir: Path,
        *,
        pack: str = "",
        address: str = "",
        panel_url: str = "",
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.state_file = server_dir / STATE_FILE
        self.pack = pack
        self.address = address
        self.panel_url = panel_url
        self.bridge: Bridge | None = None
        self.state = ServerState()
        self._message_id: int | None = None
        self._shown: str | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self._message_id = self._load()
        await self._publish()
        self._spawn(self._refresh_loop())

    async def stop(self, *, offline: bool) -> None:
        for task in self._tasks:
            task.cancel()
        if offline:
            self.state = ServerState(phase="offline")
            await self._publish()

    async def on_event(self, event: dict[str, Any]) -> None:
        match event.get("event"):
            case "server_started":
                self.state.phase = "online"
                await self.refresh()
            case "server_stopping":
                self.state = ServerState(phase="offline")
                await self._publish()
            case "join" | "leave":
                self._spawn(self._refresh_later())

    async def refresh(self) -> None:
        """Список игроков с сервера. Пока мод не ответил после старта — остаёмся в «запускается»."""
        if self.bridge is None or not self.bridge.connected or self.state.phase == "offline":
            return
        try:
            result = await self.bridge.request("online")
        except BridgeError:
            return
        self.state = ServerState(
            phase="online",
            players=[str(p) for p in result.get("players", [])],
            max_players=result.get("max"),
        )
        await self._publish()

    async def _refresh_later(self) -> None:
        await asyncio.sleep(EVENT_DELAY_SECONDS)
        await self.refresh()

    async def _refresh_loop(self) -> None:
        # Первая сверка вскоре после старта: если перезапустили только brain, события server_started не будет.
        delay = FIRST_REFRESH_SECONDS
        while True:
            await asyncio.sleep(delay)
            delay = REFRESH_SECONDS
            with contextlib.suppress(Exception):
                await self.refresh()

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publish(self) -> None:
        text = render(self.state, pack=self.pack, address=self.address)
        async with self._lock:
            if text == self._shown:
                return
            try:
                if self._message_id is not None and await self._edit(text):
                    self._shown = text
                    return
                await self._post(text)
                self._shown = text
            except TelegramAPIError:
                log.exception("статус: не удалось обновить закреплённое сообщение")

    async def _edit(self, text: str) -> bool:
        """False — сообщения больше нет (удалили), надо отправить новое."""
        try:
            await self.bot.edit_message_text(
                text, chat_id=self.chat_id, message_id=self._message_id, reply_markup=keyboard(self.panel_url)
            )
        except TelegramBadRequest as error:
            if "not modified" in error.message:
                return True
            if "not found" in error.message or "can't be edited" in error.message:
                return False
            raise
        return True

    async def _post(self, text: str) -> None:
        message = await self.bot.send_message(
            self.chat_id, text, reply_markup=keyboard(self.panel_url), disable_notification=True
        )
        self._message_id = message.message_id
        self._save()
        try:
            await self.bot.pin_chat_message(self.chat_id, message.message_id, disable_notification=True)
        except TelegramAPIError as error:
            log.warning("статус: не удалось закрепить (нужны права админа «закреплять сообщения»): %s", error)

    def _load(self) -> int | None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("chat_id") != self.chat_id or not isinstance(data.get("message_id"), int):
            return None
        return data["message_id"]

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps({"chat_id": self.chat_id, "message_id": self._message_id}), encoding="utf-8"
            )
        except OSError:
            log.exception("статус: не удалось сохранить id сообщения")
