"""Вопросы `/ai` из игры: контекст игрока → LLM → короткий ответ в игровой чат (+ копия в Telegram)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from . import prompts
from .llm import Assistant

log = logging.getLogger(__name__)

# Повторный /ai в течение этого времени продолжает разговор игрока.
SESSION_TTL_SECONDS = 15 * 60

Send = Callable[[dict[str, Any]], Awaitable[bool]]
Mirror = Callable[[str, str, str], Awaitable[None]]


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
        if (saved := self._sessions.get(key)) and time.monotonic() - saved[1] < SESSION_TTL_SECONDS:
            session_id = saved[0]
        log.info("игра: вопрос от %s: %r", player, question[:200])
        answer = await self.assistant.ask(
            build_prompt(player, question, message.get("context")),
            system_prompt=prompts.GAME,
            session_id=session_id,
        )
        if answer.session_id:
            self._sessions[key] = (answer.session_id, time.monotonic())
        await self._reply(question_id, answer.text)
        if self.mirror is not None:
            await self.mirror(player, question, answer.text)

    async def _reply(self, question_id: Any, text: str) -> None:
        if not await self.send({"type": "ai_answer", "id": question_id, "text": text}):
            log.warning("игра: не удалось отправить ответ — мод отключился")
