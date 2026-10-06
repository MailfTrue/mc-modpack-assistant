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
    "ender_chest": [
        {"id": "minecraft:shulker_box", "count": 1, "contents": {"items": [{"id": "minecraft:diamond", "count": 5}]}}
    ],
    "worn_backpack": {
        "id": "travelersbackpack:standard",
        "count": 1,
        "contents": {
            "Inventory": [{"id": "minecraft:coal", "count": 40}],
            "ToolsInventory": [{"id": "minecraft:iron_pickaxe", "count": 1}],
        },
    },
    "accessories": [
        {"slot": "ring", "items": [{"id": "artifacts:onion_ring", "count": 1}]},
        {"slot": "back", "items": [], "cosmetic": [{"id": "mymod:cape", "count": 1}]},
    ],
}


def test_format_inventory():
    text = format_inventory(
        INVENTORY, {"minecraft:diamond_sword": "Diamond Sword / Алмазный меч [minecraft:diamond_sword]"}
    )
    assert "Броня: голова — minecraft:iron_helmet [minecraft:iron_helmet] (прочность 120/165)" in text
    assert "В руке: Diamond Sword / Алмазный меч [minecraft:diamond_sword] (чары: minecraft:sharpness 3)" in text
    assert "32× minecraft:torch" in text
    assert "Инвентарь: 128× minecraft:cobblestone" in text
    assert "Эндер-сундук: minecraft:shulker_box [minecraft:shulker_box] [внутри: 5× minecraft:diamond" in text
    assert "Рюкзак на спине: travelersbackpack:standard" in text
    assert "[хранилище: 40× minecraft:coal [minecraft:coal] | инструменты: minecraft:iron_pickaxe" in text
    assert "Аксессуары: ring — artifacts:onion_ring [artifacts:onion_ring]; " in text
    assert "back — пусто (внешний вид: mymod:cape [mymod:cape])" in text


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


ME = {
    "source": "беспроводной терминал",
    "powered": True,
    "total_types": 3,
    "items": [
        {"id": "minecraft:iron_ingot", "name": "Iron Ingot", "amount": 1200},
        {"id": "minecraft:cobblestone", "name": "Cobblestone", "amount": 900},
        {"id": "minecraft:water", "type": "ae2:f", "amount": 81000},
    ],
    "craftable": ["minecraft:iron_ingot", "ae2:logic_processor"],
}


def test_me_storage_query_uses_russian_names():
    from modpack_brain.knowledge.live import format_me_storage

    names = {"minecraft:iron_ingot": "Iron Ingot / Железный слиток [minecraft:iron_ingot]"}
    text = format_me_storage(ME, names, "железный")
    assert "видов ресурсов 3, рецептов автокрафта 2" in text
    assert "- Iron Ingot / Железный слиток [minecraft:iron_ingot]: 1200 (есть автокрафт)" in text
    assert "Cobblestone" not in text


def test_me_storage_top_and_craft_only():
    from modpack_brain.knowledge.live import format_me_storage

    assert "Крупнейшие запасы" in format_me_storage(ME, {})
    text = format_me_storage(ME, {}, "processor")
    assert "можно заказать автокрафтом: ae2:logic_processor" in text
