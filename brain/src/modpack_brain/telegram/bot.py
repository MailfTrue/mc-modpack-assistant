"""Telegram-бот: вопросы к ИИ в группе и уведомления о событиях сервера."""

from __future__ import annotations

import html
import logging
import re
from collections import OrderedDict
from datetime import date

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from .. import prompts
from ..llm import Assistant, Image
from .format import render

log = logging.getLogger(__name__)

HELP = (
    "Я помощник по сборке <b>Prominence II</b>.\n\n"
    "Как спросить:\n"
    "• <code>/ai как сделать …</code>\n"
    "• упомянуть меня в сообщении\n"
    "• ответить (reply) на мой ответ — продолжу разговор с контекстом\n"
    "• можно приложить скриншот\n\n"
    "<code>/chatid</code> — показать id этого чата."
)


class LRU(OrderedDict[tuple[int, int], str]):
    def __init__(self, capacity: int) -> None:
        super().__init__()
        self.capacity = capacity

    def put(self, key: tuple[int, int], value: str) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.capacity:
            self.popitem(last=False)


class TelegramBot:
    def __init__(
        self,
        token: str,
        assistant: Assistant,
        *,
        allowed_chat_ids: list[int],
        events_chat_id: int | None,
        questions_per_user_per_day: int,
    ) -> None:
        self.bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
        self.assistant = assistant
        self.allowed = set(allowed_chat_ids)
        self.events_chat_id = events_chat_id
        self.daily_limit = questions_per_user_per_day
        # (chat_id, id сообщения бота) → id сессии LLM, чтобы reply продолжал разговор.
        self._sessions = LRU(capacity=5000)
        self._busy: set[int] = set()
        self._usage: dict[tuple[int, date], int] = {}
        self._me_id: int | None = None
        self._me_username = ""
        self.router = self._build_router()

    async def setup(self) -> None:
        me = await self.bot.get_me()
        self._me_id = me.id
        self._me_username = me.username or ""
        log.info("telegram: бот @%s, разрешённые чаты: %s", self._me_username, sorted(self.allowed) or "нет")
        if not self.allowed:
            log.warning("telegram: ALLOWED_CHAT_IDS пуст — бот отвечает только на /chatid")

    async def notify(self, text: str, *, silent: bool = False) -> None:
        """Сообщение в чат событий сервера."""
        if self.events_chat_id is None:
            return
        try:
            await self.bot.send_message(self.events_chat_id, text, disable_notification=silent)
        except Exception:
            log.exception("telegram: не удалось отправить событие")

    # ---------- маршрутизация ----------

    def _build_router(self) -> Router:
        router = Router(name="modpack")
        router.message.register(self._chat_id, Command("chatid"))
        router.message.register(self._help, Command("start", "help"), F.chat.id.func(self._is_allowed))
        router.message.register(self._ai_command, Command("ai"), F.chat.id.func(self._is_allowed))
        router.message.register(self._maybe_question, F.chat.id.func(self._is_allowed))
        return router

    def _is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.allowed

    async def _chat_id(self, message: Message) -> None:
        await message.reply(f"id этого чата: <code>{message.chat.id}</code>")

    async def _help(self, message: Message) -> None:
        await message.reply(HELP)

    async def _ai_command(self, message: Message, command: CommandObject) -> None:
        await self._answer(message, (command.args or "").strip())

    async def _maybe_question(self, message: Message) -> None:
        """Упоминание бота, reply на его сообщение или любое сообщение в личке."""
        text = message.text or message.caption or ""
        mention = f"@{self._me_username}" if self._me_username else None
        replied_to_me = (
            message.reply_to_message is not None
            and message.reply_to_message.from_user is not None
            and message.reply_to_message.from_user.id == self._me_id
        )
        is_private = message.chat.type == ChatType.PRIVATE
        mentioned = bool(mention) and mention.lower() in text.lower()
        if not (mentioned or replied_to_me or is_private):
            return  # обычная болтовня в группе — не наше дело (мост в игру появится в M4)
        if mention:
            text = re.sub(re.escape(mention), "", text, flags=re.IGNORECASE)
        await self._answer(message, text.strip())

    # ---------- вопрос → ответ ----------

    async def _answer(self, message: Message, question: str) -> None:
        user = message.from_user
        if user is None:
            return
        images = await self._images(message)
        reply = message.reply_to_message
        session_id = self._sessions.get((message.chat.id, reply.message_id)) if reply else None
        if reply is not None and session_id is None:
            # Ответ на чужое сообщение: берём его как контекст (и картинку оттуда).
            quoted = reply.text or reply.caption
            if quoted:
                question = f"Контекст — сообщение, на которое отвечают:\n«{quoted}»\n\n{question}".strip()
            images += await self._images(reply)
        if not question and not images:
            await message.reply("Напиши вопрос после /ai, например: <code>/ai с чего начать?</code>")
            return
        if user.id in self._busy:
            await message.reply("Я ещё думаю над твоим прошлым вопросом, подожди немного 🙂")
            return
        key = (user.id, date.today())
        if self._usage.get(key, 0) >= self.daily_limit:
            await message.reply(f"На сегодня лимит вопросов ({self.daily_limit}) исчерпан, приходи завтра.")
            return

        self._usage[key] = self._usage.get(key, 0) + 1
        self._busy.add(user.id)
        log.info("telegram: вопрос от %s (%d): %r", user.full_name, user.id, question[:200])
        try:
            prompt = f"Вопрос от игрока {user.full_name}:\n{question or 'Что на скриншоте?'}"
            async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
                answer = await self.assistant.ask(
                    prompt, system_prompt=prompts.TELEGRAM, images=images, session_id=session_id
                )
            await self._send_answer(message, answer.text, answer.session_id)
        finally:
            self._busy.discard(user.id)

    async def _send_answer(self, message: Message, text: str, session_id: str | None) -> None:
        target = message
        for chunk in render(text):
            try:
                sent = await target.reply(chunk)
            except TelegramBadRequest as error:
                log.warning("telegram: HTML не принят (%s), шлю как текст", error)
                sent = await target.reply(_strip_tags(chunk), parse_mode=None)
            if session_id:
                self._sessions.put((sent.chat.id, sent.message_id), session_id)
            target = sent

    async def _images(self, message: Message) -> list[Image]:
        file_id, media_type = None, "image/jpeg"
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document and (message.document.mime_type or "").startswith("image/"):
            file_id, media_type = message.document.file_id, message.document.mime_type or media_type
        if file_id is None:
            return []
        data = await self.bot.download(file_id)
        return [Image(data.read(), media_type)] if data else []


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))
