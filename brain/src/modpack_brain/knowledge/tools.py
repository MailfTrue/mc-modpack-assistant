"""Инструменты знаний для агента: in-process MCP-сервер `pack` (имена вида mcp__pack__find_item)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from .live import LiveServer
from .query import Knowledge

SERVER_NAME = "pack"
TOOL_NAMES = [
    f"mcp__{SERVER_NAME}__{name}"
    for name in (
        "find_item",
        "item_recipes",
        "tag_items",
        "list_mods",
        "search_quests",
        "team_progress",
        "player_inventory",
    )
]


def build_server(knowledge: Knowledge, live: LiveServer | None = None) -> McpSdkServerConfig:
    async def run(fn: Callable[..., str], *args: Any) -> dict[str, Any]:
        if not knowledge.available():
            text = "Индекс сборки ещё не построен (сервер не делал выгрузку). Ищи по файлам."
        else:
            # SQLite — синхронный; не держим цикл событий.
            text = await asyncio.to_thread(fn, *args)
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "find_item",
        "Найти предмет/блок сборки по названию (англ. или рус., можно часть) или id. "
        "Возвращает точные id и сколько есть рецептов. Начинай с него, если не знаешь точный id.",
        {"query": Annotated[str, "название или id, например 'mythril ingot' или 'minecraft:iron_ingot'"]},
    )
    async def find_item(args: dict[str, Any]) -> dict[str, Any]:
        return await run(knowledge.find_item, str(args.get("query", "")))

    @tool(
        "item_recipes",
        "Точные рецепты с сервера (итоговые: с датапаками и изменениями сборки). "
        "mode='produce' — как получить предмет; mode='use' — где он используется как ингредиент.",
        {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "точный id, например 'minecraft:iron_pickaxe'"},
                "mode": {"type": "string", "enum": ["produce", "use"], "description": "по умолчанию produce"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "по умолчанию 8"},
            },
            "required": ["item_id"],
        },
    )
    async def item_recipes(args: dict[str, Any]) -> dict[str, Any]:
        mode = "use" if args.get("mode") == "use" else "produce"
        limit = int(args.get("limit") or 8)
        return await run(knowledge.item_recipes, str(args.get("item_id", "")), mode, limit)

    @tool("tag_items", "Какие предметы входят в тег, например 'c:ingots/iron'.", {"tag": str})
    async def tag_items(args: dict[str, Any]) -> dict[str, Any]:
        return await run(knowledge.tag_items, str(args.get("tag", "")))

    @tool(
        "list_mods",
        "Установленные на сервере моды с версиями. query — фильтр по названию/id (пусто — все).",
        {"type": "object", "properties": {"query": {"type": "string"}}},
    )
    async def list_mods(args: dict[str, Any]) -> dict[str, Any]:
        return await run(knowledge.mods, str(args.get("query", "")))

    @tool(
        "search_quests",
        "Поиск по квестам сборки (книга квестов FTB — главный гайд по прогрессии): название, глава, задачи, "
        "награды, требования и описание. Квесты на английском — ищи английскими словами (босс, предмет, глава).",
        {"query": Annotated[str, "например 'gauntlet', 'hasturian era', 'mythril'"]},
    )
    async def search_quests(args: dict[str, Any]) -> dict[str, Any]:
        return await run(knowledge.search_quests, str(args.get("query", "")))

    @tool(
        "team_progress",
        "Прогресс по квестам на сервере: сколько выполнено по главам, последние выполненные и какие квесты "
        "доступны сейчас. Для вопросов «что нам делать дальше», «на каком мы этапе».",
        {
            "type": "object",
            "properties": {"player": {"type": "string", "description": "ник игрока (пусто — все команды)"}},
        },
    )
    async def team_progress(args: dict[str, Any]) -> dict[str, Any]:
        return await run(knowledge.team_progress, str(args.get("player", "")))

    @tool(
        "player_inventory",
        "Текущий инвентарь игрока онлайн (прямо с сервера): броня, руки, хотбар, инвентарь, эндер-сундук, "
        "чары и прочность. Для вопросов «что у меня есть», «что улучшить», «хватит ли ресурсов на крафт».",
        {"player": Annotated[str, "ник игрока в Minecraft"]},
    )
    async def player_inventory(args: dict[str, Any]) -> dict[str, Any]:
        if live is None:
            text = "Инвентарь недоступен в этом режиме."
        else:
            text = await live.inventory(str(args.get("player", "")))
        return {"content": [{"type": "text", "text": text}]}

    tools = [find_item, item_recipes, tag_items, list_mods, search_quests, team_progress, player_inventory]
    return create_sdk_mcp_server(SERVER_NAME, tools=tools)
