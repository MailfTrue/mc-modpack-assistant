"""Вопросы `/ai` из игры: контекст игрока → LLM → короткий ответ в игровой чат (+ копия в Telegram)."""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from . import prompts
from .llm import Assistant

log = logging.getLogger(__name__)

# Повторный /ai в течение этого времени продолжает разговор игрока.
SESSION_TTL_SECONDS = 15 * 60
# Сколько ответов помнить для кнопки «уточнить» (/ai re <id>) и reply из Telegram.
MAX_ANSWERS = 2000
# Длинные ответы мод показывает книгой (до ~100 страниц); сверх этого обрезаем — полный текст в Telegram.
GAME_MAX_CHARS = 12000

Send = Callable[[dict[str, Any]], Awaitable[bool]]
# (игрок, вопрос, ответ, id сессии LLM) — копия в Telegram, reply на неё продолжит этот разговор.
Mirror = Callable[[str, str, str, str | None], Awaitable[None]]


def clip_for_game(text: str, *, mirrored: bool, limit: int = GAME_MAX_CHARS) -> str:
    """Длинный ответ залил бы весь игровой чат: обрезаем по границе абзаца/строки, полный — в Telegram."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for separator in ("\n\n", "\n", ". "):
        position = cut.rfind(separator)
        if position > limit // 2:
            cut = cut[:position]
            break
    tail = "полный ответ — в Telegram" if mirrored else "спроси подробнее отдельным вопросом"
    return f"{cut.rstrip()}\n…({tail})"


def build_prompt(player: str, question: str, context: dict[str, Any] | None) -> str:
    prompt = f"Вопрос от игрока {player} (в игре):\n{question}"
    if context:
        prompt += "\n\nКонтекст игрока (данные из игры):\n" + json.dumps(context, ensure_ascii=False, indent=1)
    return prompt


class GameAi:
    def __init__(self, assistant: Assistant, send: Send, mirror: Mirror | None, daily_limit: int) -> None:
        self.assistant = assistant
        self.send = send
        self.mirror = mirror
        self.daily_limit = daily_limit
        self._sessions: dict[str, tuple[str, float]] = {}
        self._usage: dict[tuple[str, date], int] = {}
        # id вопроса (он же id ответа в игре) → сессия LLM.
        self._answers: OrderedDict[str, str] = OrderedDict()

    async def handle(self, message: dict[str, Any]) -> None:
        question_id = message.get("id")
        player = str(message.get("player") or "?")
        key = str(message.get("uuid") or player)
        question = str(message.get("question") or "").strip()
        if not question:
            await self._reply(question_id, "Напиши вопрос после /ai.")
            return
        usage_key = (key, date.today())
        if self._usage.get(usage_key, 0) >= self.daily_limit:
            await self._reply(question_id, f"На сегодня лимит вопросов ({self.daily_limit}) исчерпан.")
            return
        self._usage[usage_key] = self._usage.get(usage_key, 0) + 1

        session_id = None
        if continue_id := message.get("continue"):
            session_id = self._answers.get(str(continue_id))
            if session_id is None:
                await self._reply(question_id, "Этот разговор я уже не помню — спроси заново через /ai.")
                return
        elif (saved := self._sessions.get(key)) and time.monotonic() - saved[1] < SESSION_TTL_SECONDS:
            session_id = saved[0]
        log.info("игра: вопрос от %s: %r", player, question[:200])
        answer = await self.assistant.ask(
            build_prompt(player, question, message.get("context")),
            system_prompt=prompts.GAME,
            session_id=session_id,
        )
        if answer.session_id:
            self._sessions[key] = (answer.session_id, time.monotonic())
            if question_id is not None:
                self._answers[str(question_id)] = answer.session_id
                while len(self._answers) > MAX_ANSWERS:
                    self._answers.popitem(last=False)
        await self._reply(question_id, clip_for_game(answer.text, mirrored=self.mirror is not None))
        if self.mirror is not None:
            await self.mirror(player, question, answer.text, answer.session_id)

    async def _reply(self, question_id: Any, text: str) -> None:
        if not await self.send({"type": "ai_answer", "id": question_id, "text": text}):
            log.warning("игра: не удалось отправить ответ — мод отключился")
