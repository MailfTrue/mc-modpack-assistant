"""Единственное место, где мы общаемся с LLM (Claude Agent SDK через подписку Claude Code).

Чтобы перейти на другой бэкенд (opencode, API), достаточно переписать этот модуль, сохранив `Assistant.ask`.
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookContext,
    HookMatcher,
    ResultMessage,
    ToolUseBlock,
    query,
)

log = logging.getLogger(__name__)

# Встроенные инструменты Claude Code, которые вообще видит агент. Ни Bash, ни Write/Edit тут нет.
# Каждый вызов проходит через хук `_pre_tool_use`: веб разрешён, файлы — только в папке сервера.
# Именно хук, а не can_use_tool: Claude Code сам разрешает чтение внутри cwd, не спрашивая can_use_tool.
TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
WEB_TOOLS = ("WebSearch", "WebFetch")

# Файлы сервера, которые агенту читать незачем: пароли, токен моста, списки игроков.
DENIED_FILES = {
    "server.properties",
    "config/modpack-bridge.json",
    "ops.json",
    "banned-ips.json",
    "banned-players.json",
    "whitelist.json",
    "usercache.json",
    "usernamecache.json",
}
DENIED_SUFFIXES = (".env",)
_DENIED_NAMES = {Path(name).name for name in DENIED_FILES}

# Второй слой: правила Claude Code. В отличие от хука, они вырезают закрытые файлы и из результатов
# широкого Grep/Glob (например, Grep по всей папке config/), а не только из прямых обращений.
_DENY_SETTINGS = json.dumps(
    {"permissions": {"deny": [f"Read(./{name})" for name in sorted(DENIED_FILES)] + ["Read(**/*.env)"]}}
)


@dataclass(frozen=True)
class Image:
    data: bytes
    media_type: str = "image/jpeg"


@dataclass
class Answer:
    text: str
    session_id: str | None
    ok: bool = True
    cost_usd: float | None = None
    turns: int = 0
    tools_used: list[str] = field(default_factory=list)


class Assistant:
    def __init__(
        self,
        server_dir: Path,
        *,
        model: str,
        max_turns: int,
        timeout: float,
        max_parallel: int = 2,
    ) -> None:
        self.server_dir = server_dir.resolve()
        self.model = model
        self.max_turns = max_turns
        self.timeout = timeout
        self._slots = asyncio.Semaphore(max_parallel)

    async def ask(
        self,
        question: str,
        *,
        system_prompt: str,
        images: list[Image] | None = None,
        session_id: str | None = None,
    ) -> Answer:
        options = ClaudeAgentOptions(
            tools=TOOLS,
            hooks={"PreToolUse": [HookMatcher(hooks=[self._pre_tool_use])]},
            # Всё, что хук не разрешил явно, отклоняется без вопросов.
            permission_mode="dontAsk",
            system_prompt=system_prompt,
            model=self.model,
            max_turns=self.max_turns,
            cwd=self.server_dir,
            resume=session_id,
            # Изоляция от личных настроек Claude Code на этом ПК (режимы прав, хуки, CLAUDE.md, MCP).
            setting_sources=[],
            settings=_DENY_SETTINGS,
            strict_mcp_config=True,
        )
        tools_used: list[str] = []
        result: ResultMessage | None = None
        async with self._slots:
            try:
                async with asyncio.timeout(self.timeout):
                    # Дочитываем поток до конца: ранний выход из генератора SDK ломает его закрытие.
                    async for message in query(prompt=_prompt(question, images or []), options=options):
                        if isinstance(message, AssistantMessage):
                            tools_used += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
                        elif isinstance(message, ResultMessage):
                            result = message
            except TimeoutError:
                log.warning("LLM: таймаут %.0f с, инструменты: %s", self.timeout, tools_used)
                return Answer("Не успел ответить за отведённое время, попробуй спросить попроще.", session_id, ok=False)
            except Exception:
                log.exception("LLM: ошибка запроса")
                return Answer("Что-то сломалось при обращении к ИИ, загляни в логи.", session_id, ok=False)
        if result is None:
            return Answer("ИИ не вернул ответ.", session_id, ok=False)
        return _answer(result, tools_used)

    async def _pre_tool_use(self, hook_input: Any, _tool_use_id: str | None, _context: HookContext) -> Any:
        tool = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input") or {}
        reason = check_tool_access(self.server_dir, tool, tool_input)
        if reason is None:
            log.debug("LLM: %s %s", tool, tool_input)
            decision = {"permissionDecision": "allow"}
        else:
            log.info("LLM: отказано %s %s: %s", tool, tool_input, reason)
            decision = {"permissionDecision": "deny", "permissionDecisionReason": reason}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}


def check_tool_access(server_dir: Path, tool: str, tool_input: dict[str, Any]) -> str | None:
    """None, если вызов разрешён; иначе причина отказа (её увидит модель)."""
    if tool in WEB_TOOLS:
        return None
    if tool not in ("Read", "Grep", "Glob"):
        return f"инструмент {tool} недоступен"
    paths = [tool_input.get(key) for key in ("file_path", "path")]
    patterns = [tool_input.get(key) for key in ("pattern", "glob")] if tool == "Glob" else [tool_input.get("glob")]
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        if ".." in pattern or Path(pattern).is_absolute():
            return "шаблон должен быть относительным и без '..'"
        if any(fnmatch.fnmatch(name, pattern.rsplit("/", 1)[-1]) for name in _DENIED_NAMES):
            return "шаблон задевает закрытые файлы"
    for raw in paths:
        if raw is None:
            continue
        if not isinstance(raw, str):
            return "некорректный путь"
        path = Path(raw)
        resolved = (path if path.is_absolute() else server_dir / path).resolve()
        if not resolved.is_relative_to(server_dir):
            return f"доступна только папка сервера {server_dir}"
        relative = resolved.relative_to(server_dir).as_posix()
        if relative in DENIED_FILES or relative.endswith(DENIED_SUFFIXES):
            return "этот файл закрыт"
    return None


async def _prompt(question: str, images: list[Image]) -> AsyncIterator[dict[str, Any]]:
    # Потоковый ввод нужен для картинок и для can_use_tool.
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": img.media_type, "data": base64.b64encode(img.data).decode()},
        }
        for img in images
    ]
    content.append({"type": "text", "text": question})
    yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}


def _answer(result: ResultMessage, tools_used: list[str]) -> Answer:
    log.info(
        "LLM: %s, ходов %d, %.1f с, $%.4f, инструменты: %s",
        result.subtype,
        result.num_turns,
        result.duration_ms / 1000,
        result.total_cost_usd or 0,
        tools_used,
    )
    if result.is_error or not result.result:
        if result.subtype == "error_max_turns":
            text = "Слишком долго искал и не уложился в лимит шагов. Попробуй уточнить вопрос."
        else:
            text = "ИИ вернул ошибку: " + "; ".join(result.errors or [result.subtype])
        return Answer(text, result.session_id, ok=False, turns=result.num_turns, tools_used=tools_used)
    return Answer(
        result.result,
        result.session_id,
        cost_usd=result.total_cost_usd,
        turns=result.num_turns,
        tools_used=tools_used,
    )
