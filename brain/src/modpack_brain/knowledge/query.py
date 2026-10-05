"""Запросы к индексу знаний. Ответы — готовый текст для LLM (с точными id, чтобы их можно было цитировать)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MAX_ITEMS = 15
MAX_RECIPES = 8
MAX_TAG_PREVIEW = 3
GRID_SYMBOLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ID = re.compile(r"^#?[a-z0-9_.-]+:[a-z0-9_./-]+$")
_ID_IN_TEXT = re.compile(r"(?<![#\w])([a-z0-9_.-]+:[a-z0-9_./-]+)")


MAX_QUESTS = 6
MAX_AVAILABLE = 15


class Knowledge:
    def __init__(self, db_path: Path, server_dir: Path | None = None) -> None:
        self.db_path = db_path
        # knowledge.db лежит в <сервер>/modpack-bridge/
        self.server_dir = server_dir or db_path.parent.parent

    def available(self) -> bool:
        return self.db_path.exists()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # Соединение на каждый вызов и сразу закрываем: иначе на Windows не заменить файл при переиндексации.
        db = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    # ---------- предметы ----------

    def find_item(self, query: str) -> str:
        query = query.strip()
        if not query:
            return "Пустой запрос."
        with self._db() as db:
            rows = []
            if _ID.match(query.lower()):
                rows = db.execute("SELECT * FROM items WHERE id = ?", (query.lower().lstrip("#"),)).fetchall()
            if not rows:
                rows = db.execute(
                    "SELECT items.* FROM items_fts JOIN items ON items.rowid = items_fts.rowid "
                    "WHERE items_fts MATCH ? ORDER BY bm25(items_fts, 2.0, 5.0, 5.0) LIMIT ?",
                    (_fts_query(query), MAX_ITEMS),
                ).fetchall()
            if not rows:
                like = f"%{query.lower()}%"
                rows = db.execute(
                    "SELECT * FROM items WHERE lower(name_en) LIKE ? OR lower(coalesce(name_ru, '')) LIKE ? "
                    "OR id LIKE ? LIMIT ?",
                    (like, like, like, MAX_ITEMS),
                ).fetchall()
            if not rows:
                return f"Предметов по запросу «{query}» не найдено. Попробуй другое название (англ./рус.) или часть id."
            lines = [f"Найдено {len(rows)}:"]
            for row in rows:
                ru = f" / {row['name_ru']}" if row["name_ru"] else ""
                made = db.execute("SELECT count(*) FROM recipes WHERE result = ?", (row["id"],)).fetchone()[0]
                lines.append(f"- {row['name_en']}{ru} — {row['id']} (рецептов получения: {made})")
            return "\n".join(lines)

    # ---------- рецепты ----------

    def item_recipes(self, item_id: str, mode: str = "produce", limit: int = MAX_RECIPES) -> str:
        item_id = item_id.strip().lower()
        limit = max(1, min(limit, 20))
        with self._db() as db:
            if mode == "use":
                inputs = [
                    item_id,
                    *(f"#{tag}" for (tag,) in db.execute("SELECT tag FROM tags WHERE item = ?", (item_id,))),
                ]
                marks = ",".join("?" * len(inputs))
                rows = db.execute(
                    "SELECT DISTINCT recipes.* FROM recipe_inputs "
                    "JOIN recipes ON recipes.id = recipe_inputs.recipe_id "
                    f"WHERE recipe_inputs.input IN ({marks}) ORDER BY recipes.type, recipes.id",
                    inputs,
                ).fetchall()
                title = f"Где используется {self._name(db, item_id)}"
            else:
                rows = db.execute("SELECT * FROM recipes WHERE result = ? ORDER BY type, id", (item_id,)).fetchall()
                title = f"Как получить {self._name(db, item_id)}"
            if not rows:
                exists = db.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
                if not exists:
                    return f"Предмета {item_id} нет на сервере. Найди точный id через find_item."
                if mode == "use":
                    return f"{title}: рецептов, где он ингредиент, нет."
                return (
                    f"{title}: рецептов крафта нет. Вероятно, добывается иначе (дроп, лут, торговля, квест) "
                    "или создаётся механикой мода — поищи в квестах и в интернете."
                )
            shown = rows[:limit]
            parts = [f"{title} — рецептов: {len(rows)}" + (f", показаны первые {limit}" if len(rows) > limit else "")]
            parts += [self._format_recipe(db, row) for row in shown]
            return "\n\n".join(parts)

    def tag_items(self, tag: str) -> str:
        tag = tag.strip().lstrip("#").lower()
        with self._db() as db:
            items = [r[0] for r in db.execute("SELECT item FROM tags WHERE tag = ? ORDER BY item", (tag,))]
            if not items:
                return f"Тега #{tag} нет."
            return f"#{tag} ({len(items)}): " + ", ".join(f"{self._name(db, i)}" for i in items[:50])

    def mods(self, query: str = "") -> str:
        like = f"%{query.strip().lower()}%"
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM mods WHERE lower(id) LIKE ? OR lower(name) LIKE ? ORDER BY name", (like, like)
            ).fetchall()
        if not rows:
            return f"Модов по запросу «{query}» не найдено."
        head = f"Модов: {len(rows)}"
        return head + "\n" + "\n".join(f"- {r['name']} ({r['id']}) {r['version']}" for r in rows[:80])

    # ---------- квесты ----------

    def search_quests(self, query: str, limit: int = MAX_QUESTS) -> str:
        with self._db() as db:
            rows = db.execute(
                "SELECT quests.* FROM quests_fts JOIN quests ON quests.rowid = quests_fts.rowid "
                "WHERE quests_fts MATCH ? ORDER BY bm25(quests_fts, 8.0, 2.0, 1.0, 1.0, 3.0, 1.0) LIMIT ?",
                (_fts_query(query), max(1, min(limit, 10))),
            ).fetchall()
            if not rows:
                return f"Квестов по запросу «{query}» не найдено. Попробуй английские слова (квесты на английском)."
            return "\n\n".join(self._format_quest(db, row, full=i < 3) for i, row in enumerate(rows))

    def team_progress(self, player: str = "") -> str:
        from .quests import Quest, available, load_teams

        teams = load_teams(self.server_dir)
        if not teams:
            return "Прогресса квестов на сервере ещё нет."
        player = player.strip().lower()
        chosen = [t for t in teams if player and player in t.name.lower()] or teams
        with self._db() as db:
            rows = db.execute("SELECT * FROM quests").fetchall()
            quests = [
                Quest(
                    id=r["id"],
                    chapter_id=r["chapter_id"],
                    chapter=r["chapter"],
                    group=r["grp"],
                    title=r["title"],
                    subtitle=r["subtitle"],
                    description="",
                    tasks=[],
                    rewards=[],
                    dependencies=json.loads(r["dependencies"]),
                    min_dependencies=r["min_dependencies"],
                )
                for r in rows
            ]
        by_id = {q.id: q for q in quests}
        db_titles = self._item_names([q.title for q in quests])
        parts = []
        for team in chosen:
            done = [by_id[q] for q in team.completed if q in by_id]
            for quest in quests:
                quest.title = self._pretty(db_titles, quest.title)
            lines = [f"Команда {team.name}: выполнено квестов {len(done)} из {len(quests)}"]
            chapters: dict[str, list[int]] = {}
            for quest in quests:
                stat = chapters.setdefault(quest.chapter, [0, 0])
                stat[1] += 1
                stat[0] += quest.id in team.completed
            started = [f"{name} {d}/{t}" for name, (d, t) in chapters.items() if d]
            if started:
                lines.append("По главам: " + "; ".join(started))
            recent = sorted(done, key=lambda q: team.completed[q.id], reverse=True)[:5]
            if recent:
                lines.append("Последние выполненные: " + "; ".join(f"{q.title} [{q.chapter}]" for q in recent))
            open_now = available(quests, team.completed)
            # Сначала главы, где команда уже продвинулась: это и есть «что делать дальше».
            open_now.sort(key=lambda q: (-chapters[q.chapter][0], q.chapter))
            lines.append(f"Доступно сейчас ({len(open_now)}), первые {MAX_AVAILABLE}:")
            lines += [f"- {q.title} [{q.chapter}] (id {q.id})" for q in open_now[:MAX_AVAILABLE]]
            parts.append("\n".join(lines))
        if player and len(chosen) == len(teams) and len(teams) > 1:
            parts.insert(0, f"Команду игрока «{player}» не нашёл — показываю все.")
        return "\n\n".join(parts)

    def _item_names(self, texts: list[str]) -> dict[str, str]:
        """id предметов, упомянутых в текстах → «Название [id]»."""
        ids = {m for text in texts for m in _ID_IN_TEXT.findall(text)}
        if not ids:
            return {}
        with self._db() as db:
            return {i: self._name(db, i) for i in ids}

    @staticmethod
    def _pretty(names: dict[str, str], text: str) -> str:
        return _ID_IN_TEXT.sub(lambda m: names.get(m.group(1), m.group(1)), text)

    def _format_quest(self, db: sqlite3.Connection, row: sqlite3.Row, *, full: bool) -> str:
        names = {i: self._name(db, i) for i in _ID_IN_TEXT.findall(f"{row['title']} {row['tasks']} {row['rewards']}")}
        row = {**dict(row), **{k: self._pretty(names, row[k] or "") for k in ("title", "tasks", "rewards")}}
        lines = [f"Квест «{row['title']}» — глава {row['chapter']}" + (f" ({row['grp']})" if row["grp"] else "")]
        if row["subtitle"]:
            lines.append(f"  {row['subtitle']}")
        if row["tasks"]:
            lines.append("  Задачи: " + "; ".join(row["tasks"].split("\n")))
        if row["rewards"]:
            lines.append("  Награды: " + "; ".join(row["rewards"].split("\n")))
        deps = json.loads(row["dependencies"])
        if deps:
            marks = ",".join("?" * len(deps))
            titles = [r[0] for r in db.execute(f"SELECT title FROM quests WHERE id IN ({marks})", deps)]
            lines.append("  Требует: " + "; ".join(titles))
        if row["description"]:
            text = row["description"] if full else row["description"][:200] + "…"
            lines.append("  Описание: " + text.replace("\n", " / "))
        return "\n".join(lines)

    # ---------- форматирование ----------

    def _name(self, db: sqlite3.Connection, item_id: str) -> str:
        row = db.execute("SELECT name_en, name_ru FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return item_id
        ru = f" / {row['name_ru']}" if row["name_ru"] else ""
        return f"{row['name_en']}{ru} [{item_id}]"

    def _ingredient(self, db: sqlite3.Connection, ingredient: dict[str, Any]) -> str:
        if tag := ingredient.get("tag"):
            members = [r[0] for r in db.execute("SELECT item FROM tags WHERE tag = ? ORDER BY item", (tag,))]
            preview = ", ".join(self._name(db, i) for i in members[:MAX_TAG_PREVIEW])
            more = f" и ещё {len(members) - MAX_TAG_PREVIEW}" if len(members) > MAX_TAG_PREVIEW else ""
            return f"любой из #{tag}: {preview}{more}" if members else f"#{tag} (пустой тег)"
        items = ingredient.get("items") or []
        if len(items) == 1:
            return self._name(db, items[0])
        return "любой из: " + ", ".join(self._name(db, i) for i in items[:MAX_TAG_PREVIEW])

    def _format_recipe(self, db: sqlite3.Connection, row: sqlite3.Row) -> str:
        ingredients: list[Any] = json.loads(row["ingredients"])
        result = (
            f"{row['count'] or 1}× {self._name(db, row['result'])}" if row["result"] else "результат зависит от входа"
        )
        lines = [f"• {row['type']} ({row['id']}) → {result}"]
        if not any(ingredients):
            lines.append("  ингредиенты не раскрываются игрой (особый рецепт мода) — уточни в вики мода")
        elif row["width"] and row["height"]:
            lines += self._grid(db, ingredients, row["width"], row["height"])
        else:
            counts: dict[str, int] = {}
            for ingredient in ingredients:
                if ingredient:
                    text = self._ingredient(db, ingredient)
                    counts[text] = counts.get(text, 0) + 1
            lines += [f"  {n}× {text}" for text, n in counts.items()]
        if row["time"]:
            xp = f", опыт {row['xp']:g}" if row["xp"] else ""
            lines.append(f"  время {row['time'] / 20:g} с{xp}")
        return "\n".join(lines)

    def _grid(self, db: sqlite3.Connection, ingredients: list[Any], width: int, height: int) -> list[str]:
        symbols: dict[str, str] = {}
        rows = []
        for y in range(height):
            cells = []
            for x in range(width):
                ingredient = ingredients[y * width + x] if y * width + x < len(ingredients) else None
                if not ingredient:
                    cells.append(".")
                    continue
                key = json.dumps(ingredient, sort_keys=True)
                symbols.setdefault(key, GRID_SYMBOLS[len(symbols) % len(GRID_SYMBOLS)])
                cells.append(symbols[key])
            rows.append("    " + " ".join(cells))
        legend = [f"  {symbol} = {self._ingredient(db, json.loads(key))}" for key, symbol in symbols.items()]
        return [f"  сетка {width}×{height}:", *rows, *legend]


def _fts_query(text: str) -> str:
    words = re.findall(r"[\w:]+", text.lower())
    return " ".join(f'"{w}"*' for w in words) or '""'
