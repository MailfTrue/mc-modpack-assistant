"""Точка входа: `modpack-brain run | ask | bridge`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import prompts
from .config import Settings
from .events import format_event
from .knowledge.live import LiveServer
from .llm import Assistant

log = logging.getLogger("modpack_brain")

# События, о которых не нужно звенеть уведомлением.
SILENT_EVENTS = {"chat", "advancement", "death"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="modpack-brain", description="ИИ-помощник и мост Telegram ↔ Minecraft")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробные логи")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server-dir", type=Path, help="папка сервера (иначе SERVER_DIR из окружения или brain/.env)")
    child = argparse.ArgumentParser(add_help=False)
    child.add_argument(
        "--exit-on-stdin-eof",
        action="store_true",
        help="завершиться, когда закроется stdin (так мод останавливает brain вместе с сервером)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", parents=[common, child], help="запустить Telegram-бота и мост с модом")
    sub.add_parser(
        "bridge", parents=[common, child], help="только мост: печатать события от мода (отладка без Telegram)"
    )
    index = sub.add_parser("index", parents=[common], help="пересобрать индекс предметов и рецептов из выгрузки мода")
    index.add_argument("--force", action="store_true", help="пересобрать, даже если выгрузка не менялась")
    evaluate = sub.add_parser("eval", parents=[common], help="прогнать эталонные вопросы (eval/questions.toml)")
    evaluate.add_argument("ids", nargs="*", help="только эти вопросы (по id)")
    ask = sub.add_parser("ask", parents=[common], help="задать вопрос ИИ из консоли")
    ask.add_argument("question", nargs="+")
    args = parser.parse_args()
    if args.server_dir is not None:
        os.environ["SERVER_DIR"] = str(args.server_dir)

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
        sys.exit(f"Ошибка настроек (config/modpack-bridge.json сервера или brain/.env):\n{error}")

    try:
        if args.command == "ask":
            asyncio.run(_ask(settings, " ".join(args.question)))
        elif args.command == "eval":
            asyncio.run(_eval(settings, args.ids))
        elif args.command == "index":
            _index(settings, force=args.force)
        elif args.command == "bridge":
            asyncio.run(_bridge_only(settings, exit_on_stdin_eof=args.exit_on_stdin_eof))
        else:
            asyncio.run(_run(settings, exit_on_stdin_eof=args.exit_on_stdin_eof))
    except KeyboardInterrupt:
        log.info("остановлено")


def _assistant(settings: Settings, live: LiveServer | None = None) -> Assistant:
    from .knowledge.index import DB_FILE
    from .knowledge.query import Knowledge
    from .knowledge.tools import build_server

    knowledge = Knowledge(settings.server_dir / DB_FILE)
    if live is not None:
        live.knowledge = knowledge

    return Assistant(
        settings.server_dir,
        model=settings.llm_model,
        max_turns=settings.llm_max_turns,
        timeout=settings.llm_timeout_seconds,
        mcp_server=build_server(knowledge, live),
    )


def _index(settings: Settings, *, force: bool) -> None:
    from .knowledge.index import DB_FILE, EXPORT_DIR, ensure_index, rebuild

    export = settings.server_dir / EXPORT_DIR
    if not (export / "meta.json").exists():
        sys.exit(f"Выгрузки нет: {export}. Запусти сервер с модом — он выгружает данные при старте.")
    if force:
        rebuild(settings.server_dir)
    else:
        ensure_index(settings.server_dir)
    print(f"Индекс: {settings.server_dir / DB_FILE}")


async def _reindex(settings: Settings) -> None:
    """Пересобрать индекс в фоне, если выгрузка мода новее (при старте и по сигналу мода)."""
    from .knowledge.index import ensure_index

    try:
        await asyncio.to_thread(ensure_index, settings.server_dir)
    except Exception:
        log.exception("индекс: не удалось пересобрать")


async def _eval(settings: Settings, ids: list[str]) -> None:
    from .eval import run_eval

    await _reindex(settings)
    report = await run_eval(_assistant(settings), ids or None)
    print(f"Отчёт: {report}")


async def _ask(settings: Settings, question: str) -> None:
    answer = await _assistant(settings).ask(question, system_prompt=prompts.TELEGRAM)
    print(answer.text)
    print(
        f"\n— ходов: {answer.turns}, инструменты: {', '.join(answer.tools_used) or 'нет'}, "
        f"стоимость по ценам API: ${answer.cost_usd or 0:.4f}",
        file=sys.stderr,
    )


async def _bridge_only(settings: Settings, *, exit_on_stdin_eof: bool = False) -> None:
    """Отладка без Telegram: события и ответы /ai — в консоль.

    Ввод: /online, /inv <ник>, /me <ник> [запрос] или текст в игровой чат.
    """
    from .bridge import Bridge, BridgeError
    from .game import GameAi

    async def on_event(event: dict[str, Any]) -> None:
        print(format_event(event) or event, flush=True)

    async def on_ai_question(message: dict[str, Any]) -> None:
        await game.handle(message)

    async def mirror(player: str, question: str, answer: str) -> None:
        print(f"🎮 {player} спросил в игре: {question}\n{answer}", flush=True)

    async def on_line(line: str) -> None:
        command, _, rest = line.partition(" ")
        if command == "/inv":
            print(await live.inventory(rest), flush=True)
        elif command == "/me":
            player, _, query = rest.partition(" ")
            print(await live.me_storage(player, query), flush=True)
        elif line == "/online":
            try:
                print(await bridge.request("online"), flush=True)
            except BridgeError as error:
                print(f"/online: {error}", flush=True)
        elif line:
            await bridge.send({"type": "chat", "from": "Console", "text": line})

    async def on_data_exported(_message: dict[str, Any]) -> None:
        await _reindex(settings)

    bridge = Bridge(
        settings.bridge_host,
        settings.bridge_port,
        settings.resolve_bridge_token,
        on_event,
        on_ai_question,
        on_data_exported,
    )
    await _reindex(settings)
    live = LiveServer()
    live.bridge = bridge
    game = GameAi(_assistant(settings, live), bridge.send, mirror, settings.questions_per_user_per_day)
    await bridge.start()
    loop = asyncio.get_running_loop()
    stop = _watch_stdin(loop, None if exit_on_stdin_eof else on_line)
    await stop.wait()
    log.info("stdin закрыт — завершаюсь")
    await bridge.stop()


def _watch_stdin(
    loop: asyncio.AbstractEventLoop, on_line: Callable[[str], Awaitable[None]] | None = None
) -> asyncio.Event:
    """Событие, которое срабатывает, когда закрыт stdin (родитель-сервер остановился или умер).

    on_line — вызывать для каждой строки (интерактивная отладка).
    """
    closed = asyncio.Event()

    def wait() -> None:
        try:
            if on_line is None:
                while sys.stdin.buffer.read(4096):
                    pass
            else:
                for line in sys.stdin:
                    asyncio.run_coroutine_threadsafe(on_line(line.strip()), loop)
        except (OSError, ValueError):
            pass
        loop.call_soon_threadsafe(closed.set)

    threading.Thread(target=wait, name="stdin-watch", daemon=True).start()
    return closed


async def _run(settings: Settings, *, exit_on_stdin_eof: bool = False) -> None:
    from aiogram import Dispatcher

    from .bridge import Bridge
    from .game import GameAi
    from .telegram.bot import TelegramBot

    if settings.telegram_bot_token is None:
        sys.exit("Не задан токен Telegram: telegram.token в config/modpack-bridge.json сервера")

    live = LiveServer()
    assistant = _assistant(settings, live)
    telegram = TelegramBot(
        settings.telegram_bot_token.get_secret_value(),
        assistant,
        allowed_chat_ids=settings.allowed_chat_ids,
        events_chat_id=settings.events_chat,
        questions_per_user_per_day=settings.questions_per_user_per_day,
    )

    async def on_event(event: dict[str, Any]) -> None:
        log.info("событие: %s", {k: v for k, v in event.items() if k != "type"})
        if text := format_event(event):
            await telegram.notify(text, silent=event.get("event") in SILENT_EVENTS)

    async def on_ai_question(message: dict[str, Any]) -> None:
        await game.handle(message)

    async def on_data_exported(_message: dict[str, Any]) -> None:
        await _reindex(settings)

    bridge = Bridge(
        settings.bridge_host,
        settings.bridge_port,
        settings.resolve_bridge_token,
        on_event,
        on_ai_question,
        on_data_exported,
    )
    await _reindex(settings)
    game = GameAi(assistant, bridge.send, telegram.mirror_game_question, settings.questions_per_user_per_day)
    telegram.bridge = bridge
    live.bridge = bridge
    if settings.resolve_bridge_token() is None:
        log.warning("мост: токена пока нет — он появится после первого запуска сервера с модом")
    await bridge.start()

    await telegram.setup()
    dispatcher = Dispatcher()
    dispatcher.include_router(telegram.router)
    polling = asyncio.create_task(dispatcher.start_polling(telegram.bot, handle_signals=False))
    waiters: set[asyncio.Future[Any]] = {polling}
    if exit_on_stdin_eof:
        waiters.add(asyncio.create_task(_watch_stdin(asyncio.get_running_loop()).wait()))
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        if not polling.done():
            log.info("сервер остановился — завершаюсь")
            await asyncio.sleep(2)  # дать дойти последним уведомлениям («сервер останавливается»)
            await dispatcher.stop_polling()
        await polling
    finally:
        await bridge.stop()
        await telegram.bot.session.close()


if __name__ == "__main__":
    main()
