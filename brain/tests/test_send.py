import html
import itertools

import pytest
from aiogram.exceptions import TelegramRetryAfter

from modpack_brain.telegram import bot as bot_module
from modpack_brain.telegram.bot import TelegramBot
from modpack_brain.telegram.format import TELEGRAM_LIMIT, render, split_plain


def test_render_fits_limit_even_with_heavy_escaping():
    text = "<" * 9000  # каждый символ после экранирования становится в 4 раза длиннее
    parts = render(text)
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)
    assert html.unescape("".join(parts)) == text


def test_render_long_formatted_answer():
    text = "\n".join(f"- **пункт {i}** со `<кодом>` & ссылкой [вики](https://example.com/{i})" for i in range(800))
    parts = render(text)
    assert len(parts) > 3
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)


def test_split_plain():
    parts = split_plain("строка\n" * 2000 + "x" * 9000, limit=1000)
    assert all(0 < len(p) <= 1000 for p in parts)


class FakeMessage:
    ids = itertools.count(100)

    def __init__(self, sent: list, fail_first: int = 0) -> None:
        self.sent = sent
        self.fail_first = fail_first
        self.message_id = next(self.ids)
        self.chat = type("Chat", (), {"id": -1})()

    async def reply(self, text, **kwargs):
        if self.fail_first:
            self.fail_first -= 1
            raise TelegramRetryAfter(method=None, message="flood", retry_after=0)
        reply = FakeMessage(self.sent)
        self.sent.append((self.message_id, reply.message_id, text))
        return reply


@pytest.fixture
def telegram(monkeypatch) -> TelegramBot:
    monkeypatch.setattr(bot_module, "CHUNK_PAUSE_SECONDS", 0)
    return TelegramBot(
        "123456:TEST", assistant=None, allowed_chat_ids=[-1], events_chat_id=-1, questions_per_user_per_day=5
    )


async def test_long_answer_is_a_reply_chain_with_session(telegram: TelegramBot):
    sent: list = []
    question = FakeMessage(sent, fail_first=1)  # первая отправка упрётся в лимит частоты и повторится
    await telegram._send_answer(question, "абзац\n\n" * 1500, "sess")
    assert len(sent) > 1
    # каждая часть — reply на предыдущую
    assert all(sent[i][0] == sent[i - 1][1] for i in range(1, len(sent)))
    assert all(telegram._sessions.get((-1, reply_id)) == "sess" for _, reply_id, _ in sent)
