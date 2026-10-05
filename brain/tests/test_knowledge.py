import json
from pathlib import Path

import pytest

from modpack_brain.knowledge.index import DB_FILE, EXPORT_DIR, ensure_index, indexed_stamp
from modpack_brain.knowledge.query import Knowledge

IRON = {"items": ["minecraft:iron_ingot"]}
STICK = {"items": ["minecraft:stick"]}
EXPORT = {
    "meta": {"format": 1, "exported_at": 1000},
    "items": {
        "minecraft:iron_ingot": {"key": "item.minecraft.iron_ingot", "name": "Iron Ingot"},
        "minecraft:stick": {"key": "item.minecraft.stick", "name": "Stick"},
        "minecraft:iron_pickaxe": {"key": "item.minecraft.iron_pickaxe", "name": "Iron Pickaxe"},
        "minecraft:oak_log": {"key": "block.minecraft.oak_log", "name": "Oak Log"},
        "minecraft:oak_planks": {"key": "block.minecraft.oak_planks", "name": "Oak Planks"},
        "minecraft:raw_iron": {"key": "item.minecraft.raw_iron", "name": "Raw Iron"},
        "mymod:mythril_ingot": {"key": "item.mymod.mythril_ingot", "name": "Mythril Ingot"},
    },
    "tags": {"minecraft:oak_logs": ["minecraft:oak_log"]},
    "recipes": [
        {
            "id": "minecraft:iron_pickaxe",
            "type": "minecraft:crafting",
            "result": "minecraft:iron_pickaxe",
            "count": 1,
            "ingredients": [IRON, IRON, IRON, None, STICK, None, None, STICK, None],
            "width": 3,
            "height": 3,
        },
        {
            "id": "minecraft:oak_planks",
            "type": "minecraft:crafting",
            "result": "minecraft:oak_planks",
            "count": 4,
            "ingredients": [{"tag": "minecraft:oak_logs"}],
        },
        {
            "id": "minecraft:iron_ingot_from_smelting_raw_iron",
            "type": "minecraft:smelting",
            "result": "minecraft:iron_ingot",
            "count": 1,
            "ingredients": [{"items": ["minecraft:raw_iron"]}],
            "time": 200,
            "xp": 0.7,
        },
        {"id": "mymod:weird", "type": "mymod:infusion", "result": "mymod:mythril_ingot", "count": 1, "ingredients": []},
    ],
    "mods": [{"id": "mymod", "name": "My Mod", "version": "1.2.3"}],
}


@pytest.fixture
def server(tmp_path: Path) -> Path:
    export = tmp_path / EXPORT_DIR
    export.mkdir(parents=True)
    for name, data in EXPORT.items():
        (export / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    assert ensure_index(tmp_path)
    return tmp_path


@pytest.fixture
def knowledge(server: Path) -> Knowledge:
    return Knowledge(server / DB_FILE)


def test_find_item_by_words_prefix_and_id(knowledge: Knowledge):
    assert "minecraft:iron_ingot" in knowledge.find_item("iron ingot")
    assert "mymod:mythril_ingot" in knowledge.find_item("mythr")
    assert "Iron Pickaxe" in knowledge.find_item("minecraft:iron_pickaxe")
    assert "не найдено" in knowledge.find_item("unobtainium")


def test_shaped_recipe_as_grid(knowledge: Knowledge):
    text = knowledge.item_recipes("minecraft:iron_pickaxe")
    assert "сетка 3×3" in text
    assert "A A A" in text and ". B ." in text
    assert "A = Iron Ingot [minecraft:iron_ingot]" in text


def test_tag_ingredient_and_cooking(knowledge: Knowledge):
    assert "любой из #minecraft:oak_logs: Oak Log" in knowledge.item_recipes("minecraft:oak_planks")
    smelting = knowledge.item_recipes("minecraft:iron_ingot")
    assert "время 10 с, опыт 0.7" in smelting


def test_uses_include_tags(knowledge: Knowledge):
    assert "minecraft:iron_pickaxe" in knowledge.item_recipes("minecraft:iron_ingot", "use")
    assert "minecraft:oak_planks" in knowledge.item_recipes("minecraft:oak_log", "use")


def test_special_and_missing(knowledge: Knowledge):
    assert "не раскрываются" in knowledge.item_recipes("mymod:mythril_ingot")
    assert "рецептов крафта нет" in knowledge.item_recipes("minecraft:raw_iron")
    assert "нет на сервере" in knowledge.item_recipes("mymod:nothing")


def test_mods_and_reindex_only_when_export_changes(server: Path, knowledge: Knowledge):
    assert "My Mod (mymod) 1.2.3" in knowledge.mods("my")
    assert indexed_stamp(server / DB_FILE) == 1000
    meta = server / EXPORT_DIR / "meta.json"
    meta.write_text(json.dumps({"format": 1, "exported_at": 2000}), encoding="utf-8")
    ensure_index(server)
    assert indexed_stamp(server / DB_FILE) == 2000
