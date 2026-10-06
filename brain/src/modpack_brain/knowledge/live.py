"""Живые данные с работающего сервера через мост (инвентарь игрока и т. п.) — для инструментов агента."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .query import Knowledge

if TYPE_CHECKING:
    from ..bridge import Bridge

ARMOR_NAMES = {"head": "голова", "chest": "грудь", "legs": "ноги", "feet": "ступни"}


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
    return items


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
        return text + (f" ({'; '.join(extras)})" if extras else "")

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
    if hotbar:
        lines.append("Хотбар: " + "; ".join(f"{h['slot']}: {item(h)}" for h in hotbar))
    for key, title in (("main", "Инвентарь"), ("ender_chest", "Эндер-сундук")):
        entries = data.get(key) or []
        lines.append(f"{title}: " + ("; ".join(item(e) for e in entries) if entries else "пусто"))
    return "\n".join(lines)
