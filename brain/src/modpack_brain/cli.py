"""Точка входа: `modpack-brain run | ask`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from pydantic import ValidationError

from . import prompts
from .config import Settings
from .events import format_event
from .llm import Assistant

log = logging.getLogger("modpack_brain")

# События, о которых не нужно звенеть уведомлением.
SILENT_EVENTS = {"chat", "advancement", "death"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="modpack-brain", description="ИИ-помощник и мост Telegram ↔ Minecraft")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробные логи")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="запустить Telegram-бота и мост с модом")
    sub.add_parser("bridge", help="только мост: печатать события от мода в консоль (отладка без Telegram)")
    ask = sub.add_parser("ask", help="задать вопрос ИИ из консоли")
    ask.add_argument("question", nargs="+")
    args = parser.parse_args()

    # Windows-консоль по умолчанию не в UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        sys.exit(f"Ошибка настроек (brain/.env):\n{error}")

    try:
        if args.command == "ask":
            asyncio.run(_ask(settings, " ".join(args.question)))
        elif args.command == "bridge":
            asyncio.run(_bridge_only(settings))
        else:
            asyncio.run(_run(settings))
    except KeyboardInterrupt:
        log.info("остановлено")


def _assistant(settings: Settings) -> Assistant:
    return Assistant(
        settings.server_dir,
        model=settings.llm_model,
        max_turns=settings.llm_max_turns,
        timeout=settings.llm_timeout_seconds,
    )


async def _ask(settings: Settings, question: str) -> None:
    answer = await _assistant(settings).ask(question, system_prompt=prompts.TELEGRAM)
    print(answer.text)
    print(
        f"\n— ходов: {answer.turns}, инструменты: {', '.join(answer.tools_used) or 'нет'}, "
        f"стоимость по ценам API: ${answer.cost_usd or 0:.4f}",
        file=sys.stderr,
    )


async def _bridge_only(settings: Settings) -> None:
    from .bridge import Bridge

    async def on_event(event: dict[str, Any]) -> None:
        print(format_event(event) or event, flush=True)

    bridge = Bridge(settings.bridge_host, settings.bridge_port, settings.resolve_bridge_token, on_event)
    await bridge.start()
    await asyncio.Event().wait()


async def _run(settings: Settings) -> None:
    from aiogram import Dispatcher

    from .bridge import Bridge
    from .telegram.bot import TelegramBot

    if settings.telegram_bot_token is None:
        sys.exit("Не задан TELEGRAM_BOT_TOKEN в brain/.env")

    telegram = TelegramBot(
        settings.telegram_bot_token.get_secret_value(),
        _assistant(settings),
        allowed_chat_ids=settings.allowed_chat_ids,
        events_chat_id=settings.events_chat,
        questions_per_user_per_day=settings.questions_per_user_per_day,
    )

    async def on_event(event: dict[str, Any]) -> None:
        log.info("событие: %s", {k: v for k, v in event.items() if k != "type"})
        if text := format_event(event):
            await telegram.notify(text, silent=event.get("event") in SILENT_EVENTS)

    bridge = Bridge(settings.bridge_host, settings.bridge_port, settings.resolve_bridge_token, on_event)
    if settings.resolve_bridge_token() is None:
        log.warning("мост: токена пока нет — он появится после первого запуска сервера с модом")
    await bridge.start()

    await telegram.setup()
    dispatcher = Dispatcher()
    dispatcher.include_router(telegram.router)
    try:
        await dispatcher.start_polling(telegram.bot, handle_signals=False)
    finally:
        await bridge.stop()
        await telegram.bot.session.close()


if __name__ == "__main__":
    main()
