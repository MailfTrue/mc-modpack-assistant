"""События сервера от мода → текст для Telegram (HTML)."""

from __future__ import annotations

from html import escape
from typing import Any

_FRAMES = {"task": "🏅", "goal": "🎯", "challenge": "🏆"}


def format_event(event: dict[str, Any]) -> str | None:
    """None — событие не публикуем (неизвестное или пустое)."""
    kind = event.get("event")
    player = f"<b>{escape(str(event.get('player', '?')))}</b>"
    match kind:
        case "server_started":
            return "🟢 Сервер запущен"
        case "server_stopping":
            return "🔴 Сервер останавливается"
        case "join":
            return f"➕ {player} зашёл на сервер"
        case "leave":
            return f"➖ {player} вышел с сервера"
        case "death":
            message = event.get("message") or f"{event.get('player', '?')} умер"
            return f"💀 {escape(str(message))}"
        case "advancement":
            icon = _FRAMES.get(str(event.get("frame")), "🏅")
            title = escape(str(event.get("title", "?")))
            text = f"{icon} {player} получил достижение <b>[{title}]</b>"
            if description := event.get("description"):
                text += f"\n<i>{escape(str(description))}</i>"
            return text
        case "chat":
            message = str(event.get("message", "")).strip()
            return f"💬 {player}: {escape(message)}" if message else None
    return None
