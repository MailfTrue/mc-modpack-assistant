from modpack_brain.bridge import BridgeError
from modpack_brain.knowledge.live import LiveServer, format_inventory

INVENTORY = {
    "player": "mailf",
    "selected_hotbar_slot": 1,
    "armor": {"head": {"id": "minecraft:iron_helmet", "count": 1, "durability": "120/165"}},
    "hotbar": [
        {"id": "minecraft:diamond_sword", "count": 1, "slot": 1, "enchantments": ["minecraft:sharpness 3"]},
        {"id": "minecraft:torch", "count": 32, "slot": 2},
    ],
    "main": [{"id": "minecraft:cobblestone", "count": 128}],
    "ender_chest": [],
}


def test_format_inventory():
    text = format_inventory(
        INVENTORY, {"minecraft:diamond_sword": "Diamond Sword / Алмазный меч [minecraft:diamond_sword]"}
    )
    assert "Броня: голова — minecraft:iron_helmet [minecraft:iron_helmet] (прочность 120/165)" in text
    assert "В руке: Diamond Sword / Алмазный меч [minecraft:diamond_sword] (чары: minecraft:sharpness 3)" in text
    assert "32× minecraft:torch" in text
    assert "Инвентарь: 128× minecraft:cobblestone" in text
    assert "Эндер-сундук: пусто" in text


class FakeBridge:
    connected = True

    async def request(self, method, timeout=5.0, **params):
        if method == "online":
            return {"players": ["mailf"]}
        if params.get("player") == "mailf":
            return INVENTORY
        raise BridgeError("игрок не в сети")


async def test_live_inventory_and_offline_player():
    live = LiveServer()
    live.bridge = FakeBridge()
    assert "Инвентарь mailf" in await live.inventory("mailf")
    offline = await live.inventory("donya")
    assert "не в сети" in offline and "Сейчас в сети: mailf" in offline
    live.bridge = None
    assert "не подключён" in await live.inventory("mailf")
