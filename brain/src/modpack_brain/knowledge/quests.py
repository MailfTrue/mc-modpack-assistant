"""Квесты FTB Quests: читаемый текст из config/ftbquests и прогресс команд из world/ftbquests."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import snbt

log = logging.getLogger(__name__)

QUESTS_DIR = Path("config") / "ftbquests" / "quests"
PROGRESS_DIR = Path("world") / "ftbquests"
# Английские оригиналы квестов, если на сервер положен перевод (русская локализация сборки).
ORIGINAL_DIR = Path("modpack-bridge") / "quests-original" / "quests"
MAX_DESCRIPTION = 1500

_FORMAT = re.compile(r"&[0-9a-fk-or]", re.IGNORECASE)
_LANGUAGE_MARKER = re.compile(r"^(English|Español|Espanol|Português|Русский)$", re.IGNORECASE)


@dataclass
class Quest:
    id: str
    chapter_id: str
    chapter: str
    group: str
    title: str
    subtitle: str
    description: str
    tasks: list[str]
    rewards: list[str]
    dependencies: list[str]
    min_dependencies: int = 0
    task_ids: list[str] = field(default_factory=list)
    # Английский оригинал (если квесты на сервере переведены): для поиска на обоих языках.
    title_en: str = ""
    chapter_en: str = ""
    description_en: str = ""


def clean(text: str) -> str:
    return _FORMAT.sub("", text.replace("\\&", "&")).strip()


def load_quests(server_dir: Path) -> list[Quest]:
    """Квесты сервера; если рядом лежат английские оригиналы (ORIGINAL_DIR), добавляет их к каждому квесту."""
    quests = _load_from(server_dir / QUESTS_DIR)
    original_dir = server_dir / ORIGINAL_DIR
    if original_dir.is_dir():
        originals = {q.id: q for q in _load_from(original_dir)}
        for quest in quests:
            if (original := originals.get(quest.id)) is not None:
                quest.title_en = original.title
                quest.chapter_en = original.chapter
                quest.description_en = original.description
    return quests


def _load_from(base: Path) -> list[Quest]:
    groups: dict[str, str] = {}
    groups_file = base / "chapter_groups.snbt"
    if groups_file.exists():
        for group in _read(groups_file).get("chapter_groups", []):
            groups[str(group.get("id"))] = clean(str(group.get("title", "")))
    quests: list[Quest] = []
    for path in sorted((base / "chapters").glob("*.snbt")):
        try:
            chapter = _read(path)
        except (OSError, snbt.SnbtError) as error:
            log.warning("квесты: не разобрать %s: %s", path.name, error)
            continue
        chapter_title = clean(str(chapter.get("title") or chapter.get("filename") or path.stem))
        group = groups.get(str(chapter.get("group")), "")
        for raw in chapter.get("quests", []):
            if isinstance(raw, dict) and raw.get("id"):
                quests.append(_quest(raw, str(chapter.get("id")), chapter_title, group))
    return quests


def _read(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    data = snbt.loads(text)
    return data if isinstance(data, dict) else {}


def _quest(raw: dict[str, Any], chapter_id: str, chapter: str, group: str) -> Quest:
    tasks = [t for t in raw.get("tasks", []) if isinstance(t, dict)]
    task_texts = [_task(t) for t in tasks]
    title = clean(str(raw.get("title", ""))) or (_default_title(tasks[0]) if tasks else "") or str(raw["id"])
    return Quest(
        id=str(raw["id"]),
        chapter_id=chapter_id,
        chapter=chapter,
        group=group,
        title=title,
        subtitle=clean(str(raw.get("subtitle", ""))),
        description=_description(raw.get("description", [])),
        tasks=task_texts,
        rewards=[r for r in (_reward(x) for x in raw.get("rewards", []) if isinstance(x, dict)) if r],
        dependencies=[str(d) for d in raw.get("dependencies", [])],
        min_dependencies=int(raw.get("min_required_dependencies") or 0),
        task_ids=[str(t.get("id")) for t in tasks],
    )


def _description(lines: Any) -> str:
    if not isinstance(lines, list):
        return ""
    out: list[str] = []
    for line in lines:
        text = str(line)
        if "{@pagebreak}" in text:
            break  # дальше обычно перевод того же текста на другие языки
        text = clean(text)
        if text.startswith(("{", "[")) or _LANGUAGE_MARKER.match(text):
            continue  # картинки, json-компоненты, подписи языка
        out.append(text)
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return description[:MAX_DESCRIPTION]


def _item_id(item: Any) -> str:
    if isinstance(item, dict):
        if item.get("id") == "itemfilters:tag":
            return f"#{item.get('tag', {}).get('value', '?')}"
        count = item.get("Count") or item.get("count") or 1
        return f"{count}× {item.get('id', '?')}" if count and count != 1 else str(item.get("id", "?"))
    return str(item)


def _default_title(task: dict[str, Any]) -> str:
    """Как FTB: без явного названия квест называется по цели первой задачи (id потом заменится названием)."""
    title = clean(str(task.get("title", "")))
    if title:
        return title
    item = task.get("item")
    if isinstance(item, dict):
        item = item.get("id") if item.get("id") != "itemfilters:tag" else f"#{item.get('tag', {}).get('value', '?')}"
    for value in (item, task.get("entity"), task.get("structure"), task.get("dimension"), task.get("biome")):
        if value:
            return str(value)
    return str(task.get("type", ""))


def _task(task: dict[str, Any]) -> str:
    kind = str(task.get("type", ""))
    title = clean(str(task.get("title", "")))
    count = task.get("count") or task.get("value")
    match kind:
        case "item":
            what = f"принести/получить {_item_id(task.get('item'))}" + (f" ×{count}" if count and count != 1 else "")
        case "kill":
            what = f"убить {task.get('entity', '?')}" + (f" ×{count}" if count and count != 1 else "")
        case "advancement":
            what = f"достижение {task.get('advancement', '?')}"
        case "checkmark":
            what = "отметить галочкой (прочитать)"
        case "dimension":
            what = f"попасть в измерение {task.get('dimension', '?')}"
        case "biome":
            what = f"найти биом {task.get('biome', '?')}"
        case "structure":
            what = f"найти структуру {task.get('structure', '?')}"
        case "xp":
            what = f"набрать опыт {count}"
        case "observation":
            what = f"посмотреть на {task.get('to_observe', '?')}"
        case _:
            what = kind or "задача"
    return f"{title} ({what})" if title else what


def _reward(reward: dict[str, Any]) -> str:
    kind = str(reward.get("type", ""))
    if reward.get("auto") == "invisible" or kind in ("command", "advancement"):
        return ""
    match kind:
        case "item":
            return _item_id(reward.get("item"))
        case "xp":
            return f"{reward.get('xp')} опыта"
        case "xp_levels":
            return f"{reward.get('xp_levels')} уровней опыта"
        case "loot" | "random" | "choice" | "all_table":
            return f"награда из таблицы ({kind})"
        case _:
            return kind


# ---------- прогресс команд ----------


@dataclass
class Team:
    name: str
    completed: dict[str, int]


def load_teams(server_dir: Path) -> list[Team]:
    teams = []
    for path in sorted((server_dir / PROGRESS_DIR).glob("*.snbt")):
        try:
            data = _read(path)
        except (OSError, snbt.SnbtError) as error:
            log.warning("квесты: не разобрать прогресс %s: %s", path.name, error)
            continue
        completed = {str(k): int(v) for k, v in (data.get("completed") or {}).items() if isinstance(v, int | float)}
        teams.append(Team(name=str(data.get("name", path.stem)), completed=completed))
    return teams


def available(quests: list[Quest], completed: dict[str, int]) -> list[Quest]:
    """Не выполненные квесты, у которых выполнены зависимости (как в FTB: все или min_required)."""
    out = []
    for quest in quests:
        if quest.id in completed:
            continue
        done = sum(1 for d in quest.dependencies if d in completed)
        need = quest.min_dependencies or len(quest.dependencies)
        if done >= min(need, len(quest.dependencies)):
            out.append(quest)
    return out


def to_row(quest: Quest) -> tuple[Any, ...]:
    return (
        quest.id,
        quest.chapter_id,
        quest.chapter,
        quest.group,
        quest.title,
        quest.subtitle,
        quest.description,
        "\n".join(quest.tasks),
        "\n".join(quest.rewards),
        json.dumps(quest.dependencies),
        quest.min_dependencies,
        quest.title_en,
        quest.chapter_en,
        quest.description_en,
    )
