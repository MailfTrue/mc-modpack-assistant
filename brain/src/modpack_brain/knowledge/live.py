"""Живые данные с работающего сервера через мост (инвентарь игрока и т. п.) — для инструментов агента."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .query import Knowledge

if TYPE_CHECKING:
    from ..bridge import Bridge

ARMOR_NAMES = {"head": "голова", "chest": "грудь", "legs": "ноги", "feet": "ступни"}
# Отсеки контейнеров (ключи NBT): Traveler's Backpack и общие.
SECTION_NAMES = {
    "items": "внутри",
    "Inventory": "хранилище",
    "ToolsInventory": "инструменты",
    "CraftingInventory": "сетка крафта",
}


class LiveServer:
    """Мост появляется позже ассистента (они создаются в разном порядке), поэтому ссылка задаётся потом."""

    def __init__(self, knowledge: Knowledge | None = None) -> None:
        self.bridge: Bridge | None = None
        self.knowledge = knowledge

    async def inventory(self, player: str) -> str:
        from ..bridge import BridgeError

        player = player.strip()
        if not player:
            return "Укажи ник игрока."
        if self.bridge is None or not self.bridge.connected:
            return "Сервер сейчас не подключён — инвентарь посмотреть нельзя."
        try:
            data = await self.bridge.request("inventory", player=player)
        except BridgeError as error:
            online = await self._online()
            return f"Не удалось: {error}." + (f" Сейчас в сети: {', '.join(online)}." if online else "")
        return format_inventory(data, self._names(data))

    async def me_storage(self, player: str, query: str = "") -> str:
        from ..bridge import BridgeError

        player = player.strip()
        if not player:
            return (
                "Укажи ник игрока: ME-сеть ищется по его беспроводному терминалу или ME-блоку, на который он смотрел."
            )
        if self.bridge is None or not self.bridge.connected:
            return "Сервер сейчас не подключён — ME-сеть посмотреть нельзя."
        try:
            data = await self.bridge.request("me_storage", timeout=10.0, player=player)
        except BridgeError as error:
            return f"Не удалось: {error}"
        if "error" in data:
            return str(data["error"])
        ids = sorted({e["id"] for e in data.get("items") or []} | set(data.get("craftable") or []))
        names = self.knowledge.names(ids) if self.knowledge and self.knowledge.available() else {}
        return format_me_storage(data, names, query)

    async def _online(self) -> list[str]:
        from ..bridge import BridgeError

        try:
            return [str(p) for p in (await self.bridge.request("online")).get("players", [])]  # type: ignore[union-attr]
        except BridgeError:
            return []

    def _names(self, data: dict[str, Any]) -> dict[str, str]:
        if self.knowledge is None or not self.knowledge.available():
            return {}
        ids = {item["id"] for item in _all_items(data) if isinstance(item, dict) and "id" in item}
        return self.knowledge.names(sorted(ids))


def _all_items(data: dict[str, Any]) -> list[Any]:
    items = list((data.get("armor") or {}).values())
    if data.get("off_hand"):
        items.append(data["off_hand"])
    for key in ("hotbar", "main", "ender_chest"):
        items += data.get(key) or []
    for slot in data.get("accessories") or []:
        items += (slot.get("items") or []) + (slot.get("cosmetic") or [])
    if data.get("worn_backpack"):
        items.append(data["worn_backpack"])
    return _with_contents(items)


def _with_contents(items: list[Any]) -> list[Any]:
    """Предметы плюс всё, что лежит внутри рюкзаков и шалкеров (рекурсивно)."""
    nested = [
        i
        for item in items
        if isinstance(item, dict)
        for section in (item.get("contents") or {}).values()
        for i in section
    ]
    return items + (_with_contents(nested) if nested else [])


def format_inventory(data: dict[str, Any], names: dict[str, str]) -> str:
    def item(entry: dict[str, Any]) -> str:
        text = names.get(entry["id"]) or f"{entry.get('name', entry['id'])} [{entry['id']}]"
        if entry.get("count", 1) != 1:
            text = f"{entry['count']}× {text}"
        extras = []
        if entry.get("enchantments"):
            extras.append("чары: " + ", ".join(entry["enchantments"]))
        if entry.get("durability"):
            extras.append(f"прочность {entry['durability']}")
        text += f" ({'; '.join(extras)})" if extras else ""
        contents = entry.get("contents") or {}
        if contents:
            sections = [
                f"{SECTION_NAMES.get(name, name)}: " + ", ".join(item(i) for i in section)
                for name, section in contents.items()
            ]
            text += " [" + " | ".join(sections) + "]"
        return text

    lines = [f"Инвентарь {data.get('player', '?')}:"]
    armor = data.get("armor") or {}
    lines.append(
        "Броня: " + ("; ".join(f"{ARMOR_NAMES.get(k, k)} — {item(v)}" for k, v in armor.items()) if armor else "нет")
    )
    hotbar = data.get("hotbar") or []
    selected = data.get("selected_hotbar_slot")
    in_hand = next((h for h in hotbar if h.get("slot") == selected), None)
    lines.append("В руке: " + (item(in_hand) if in_hand else "пусто"))
    if data.get("off_hand"):
        lines.append("Во второй руке: " + item(data["off_hand"]))
    accessories = data.get("accessories")
    if accessories is not None:
        parts = []
        for slot in accessories:
            worn = ", ".join(item(i) for i in slot.get("items") or []) or "пусто"
            cosmetic = slot.get("cosmetic") or []
            if cosmetic:
                worn += " (внешний вид: " + ", ".join(item(i) for i in cosmetic) + ")"
            parts.append(f"{slot.get('slot', '?')} — {worn}")
        lines.append("Аксессуары: " + ("; ".join(parts) if parts else "ничего не надето"))
    if data.get("worn_backpack"):
        lines.append("Рюкзак на спине: " + item(data["worn_backpack"]))
    if hotbar:
        lines.append("Хотбар: " + "; ".join(f"{h['slot']}: {item(h)}" for h in hotbar))
    for key, title in (("main", "Инвентарь"), ("ender_chest", "Эндер-сундук")):
        entries = data.get(key) or []
        lines.append(f"{title}: " + ("; ".join(item(e) for e in entries) if entries else "пусто"))
    return "\n".join(lines)


MAX_ME_LINES = 30


def format_me_storage(data: dict[str, Any], names: dict[str, str], query: str = "") -> str:
    """Содержимое ME-сети: с запросом — подходящие позиции, без — крупнейшие запасы."""
    items: list[dict[str, Any]] = data.get("items") or []
    craftable = set(data.get("craftable") or [])
    power = "питание есть" if data.get("powered", True) else "⚠ НЕТ ПИТАНИЯ — содержимое может быть недоступно"
    lines = [
        f"ME-сеть ({data.get('source', '?')}): видов ресурсов {data.get('total_types', len(items))}, "
        f"рецептов автокрафта {len(craftable)}; {power}."
    ]

    def label(entry_id: str, fallback: str) -> str:
        return names.get(entry_id) or f"{fallback} [{entry_id}]"

    if query.strip():
        words = query.lower().split()

        def matches(entry_id: str, name: str) -> bool:
            text = f"{entry_id} {name} {names.get(entry_id, '')}".lower()
            return all(w in text for w in words)

        found = [e for e in items if matches(e["id"], e.get("name", ""))]
        lines.append(f"По запросу «{query}» в наличии: {len(found)}")
        lines += [
            f"- {label(e['id'], e.get('name', e['id']))}: {e['amount']}"
            + (" (есть автокрафт)" if e["id"] in craftable else "")
            for e in found[:MAX_ME_LINES]
        ]
        in_stock = {e["id"] for e in items}
        only_craft = [c for c in sorted(craftable) if c not in in_stock and matches(c, "")]
        if only_craft:
            lines.append(
                "Нет в наличии, но можно заказать автокрафтом: " + ", ".join(label(c, c) for c in only_craft[:15])
            )
    else:
        lines.append(f"Крупнейшие запасы (первые {min(MAX_ME_LINES, len(items))}):")
        lines += [f"- {label(e['id'], e.get('name', e['id']))}: {e['amount']}" for e in items[:MAX_ME_LINES]]
    return "\n".join(lines)
