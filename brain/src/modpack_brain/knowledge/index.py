"""Индекс знаний о сборке (SQLite + FTS5) из выгрузки мода `<сервер>/modpack-bridge/export`.

Выгрузку делает мод из реестров работающего сервера, поэтому в ней итоговые рецепты — с датапаками,
условиями загрузки и изменениями AlmostUnified. Индекс пересобирается целиком (это секунды).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .quests import Quest, load_quests, to_row

log = logging.getLogger(__name__)

EXPORT_DIR = Path("modpack-bridge") / "export"
DB_FILE = Path("modpack-bridge") / "knowledge.db"
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE items (
    id TEXT PRIMARY KEY, mod TEXT NOT NULL, key TEXT, name_en TEXT NOT NULL, name_ru TEXT
);
CREATE VIRTUAL TABLE items_fts USING fts5(
    id, name_en, name_ru, content='items', tokenize="unicode61 remove_diacritics 2 tokenchars '_:'"
);
CREATE TABLE recipes (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, serializer TEXT, result TEXT, count INTEGER,
    width INTEGER, height INTEGER, time INTEGER, xp REAL, ingredients TEXT NOT NULL
);
CREATE INDEX recipes_result ON recipes(result);
CREATE TABLE recipe_inputs (recipe_id TEXT NOT NULL, input TEXT NOT NULL);
CREATE INDEX recipe_inputs_input ON recipe_inputs(input);
CREATE TABLE tags (tag TEXT NOT NULL, item TEXT NOT NULL);
CREATE INDEX tags_tag ON tags(tag);
CREATE INDEX tags_item ON tags(item);
CREATE TABLE mods (id TEXT PRIMARY KEY, name TEXT, version TEXT);
CREATE TABLE quests (
    id TEXT PRIMARY KEY, chapter_id TEXT, chapter TEXT, grp TEXT, title TEXT, subtitle TEXT, description TEXT,
    tasks TEXT, rewards TEXT, dependencies TEXT, min_dependencies INTEGER
);
CREATE VIRTUAL TABLE quests_fts USING fts5(
    title, chapter, subtitle, description, tasks, rewards, content='quests',
    tokenize="unicode61 remove_diacritics 2 tokenchars '_:'"
);
"""


def export_stamp(server_dir: Path) -> int | None:
    """Время выгрузки из meta.json (мод пишет его последним), None — выгрузки нет."""
    try:
        meta = json.loads((server_dir / EXPORT_DIR / "meta.json").read_text(encoding="utf-8"))
        return int(meta["exported_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def indexed_stamp(db_path: Path) -> int | None:
    if not db_path.exists():
        return None
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as db:
            rows = dict(db.execute("SELECT key, value FROM meta").fetchall())
        if int(rows.get("schema", 0)) != SCHEMA_VERSION:
            return None
        return int(rows["exported_at"])
    except (sqlite3.Error, KeyError, ValueError):
        return None


def ensure_index(server_dir: Path) -> bool:
    """Пересобрать индекс, если выгрузка новее. True — индекс есть (новый или актуальный)."""
    db_path = server_dir / DB_FILE
    stamp = export_stamp(server_dir)
    if stamp is None:
        return db_path.exists()
    if indexed_stamp(db_path) == stamp:
        return True
    rebuild(server_dir)
    return True


def rebuild(server_dir: Path) -> None:
    """Полная пересборка: выгрузка мода + русские названия из jar-файлов и ресурспаков."""
    from .lang import load_names

    export_dir = server_dir / EXPORT_DIR
    mods = _load(export_dir / "mods.json")
    version = next((m["version"] for m in mods if m.get("id") == "minecraft"), None)
    names = load_names(server_dir, version)
    build(export_dir, server_dir / DB_FILE, ru_names=names, quests=load_quests(server_dir))


def build(
    export_dir: Path, db_path: Path, ru_names: dict[str, str] | None = None, quests: list[Quest] | None = None
) -> None:
    started = time.monotonic()
    data = {name: _load(export_dir / f"{name}.json") for name in ("meta", "items", "tags", "recipes", "mods")}
    data["ru"] = ru_names or {}
    data["quests"] = quests or []
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as db:
        db.executescript(SCHEMA)
        _fill(db, data)
        db.commit()
    _replace(tmp, db_path)
    log.info(
        "индекс: %d предметов (%d с русским названием), %d рецептов, %d тегов, %d квестов за %.1f с",
        len(data["items"]),
        sum(1 for v in data["items"].values() if v.get("key") in data["ru"]),
        len(data["recipes"]),
        len(data["tags"]),
        len(data["quests"]),
        time.monotonic() - started,
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fill(db: sqlite3.Connection, data: dict[str, Any]) -> None:
    meta = data["meta"]
    db.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("schema", str(SCHEMA_VERSION)), ("exported_at", str(meta["exported_at"])), ("format", str(meta["format"]))],
    )
    db.executemany(
        "INSERT INTO items(id, mod, key, name_en, name_ru) VALUES (?, ?, ?, ?, ?)",
        [
            (item_id, item_id.split(":", 1)[0], v.get("key"), v.get("name") or item_id, data["ru"].get(v.get("key")))
            for item_id, v in data["items"].items()
        ],
    )
    db.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
    db.executemany(
        "INSERT INTO tags VALUES (?, ?)", [(tag, item) for tag, items in data["tags"].items() for item in items]
    )
    recipes, inputs = [], []
    for r in data["recipes"]:
        recipes.append(
            (
                r["id"],
                r["type"],
                r.get("serializer"),
                r.get("result"),
                r.get("count"),
                r.get("width"),
                r.get("height"),
                r.get("time"),
                r.get("xp"),
                json.dumps(r.get("ingredients") or [], ensure_ascii=False),
            )
        )
        seen: set[str] = set()
        for ingredient in r.get("ingredients") or []:
            for key in _ingredient_keys(ingredient):
                if key not in seen:
                    seen.add(key)
                    inputs.append((r["id"], key))
    db.executemany("INSERT OR REPLACE INTO recipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", recipes)
    db.executemany("INSERT INTO recipe_inputs VALUES (?, ?)", inputs)
    db.executemany(
        "INSERT OR REPLACE INTO quests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", map(to_row, data["quests"])
    )
    db.execute("INSERT INTO quests_fts(quests_fts) VALUES ('rebuild')")
    db.executemany(
        "INSERT OR REPLACE INTO mods VALUES (?, ?, ?)", [(m["id"], m["name"], m["version"]) for m in data["mods"]]
    )


def _ingredient_keys(ingredient: Any) -> list[str]:
    if not isinstance(ingredient, dict):
        return []
    if tag := ingredient.get("tag"):
        return [f"#{tag}"]
    return [item for item in ingredient.get("items", []) if isinstance(item, str)]


def _replace(tmp: Path, target: Path) -> None:
    # На Windows замена может упасть, если файл сейчас читает инструмент — повторяем.
    for attempt in range(20):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)
