from pathlib import Path

import pytest

from modpack_brain.knowledge import snbt
from modpack_brain.knowledge.quests import Quest, available, clean, load_quests, load_teams


def test_snbt_ftb_flavour():
    data = snbt.loads(
        """{
        id: "A1"
        size: 1.5d
        count: 3L
        flag: true
        list: [I; 1, 2, 3]
        nested: { "quoted key": "a \\"b\\"", bare: minecraft:stone }
        lines: [
            "&7first"
            ""
        ]
    }"""
    )
    assert data["id"] == "A1"
    assert data["size"] == 1.5
    assert data["count"] == 3
    assert data["flag"] is True
    assert data["list"] == [1, 2, 3]
    assert data["nested"] == {"quoted key": 'a "b"', "bare": "minecraft:stone"}
    assert data["lines"] == ["&7first", ""]


def test_snbt_errors():
    with pytest.raises(snbt.SnbtError):
        snbt.loads('{a: "unterminated}')


def test_clean_color_codes():
    assert clean(r"&f&lHow To&r: &aQuesting! \& more") == "How To: Questing! & more"


@pytest.fixture
def server(tmp_path: Path) -> Path:
    quests = tmp_path / "config/ftbquests/quests"
    (quests / "chapters").mkdir(parents=True)
    (quests / "chapter_groups.snbt").write_text('{chapter_groups: [{id: "G1", title: "&6Campaign"}]}', "utf-8")
    (quests / "chapters/main.snbt").write_text(
        """{
        id: "C1"
        group: "G1"
        title: "&eMain Story"
        quests: [
            {
                id: "Q1"
                title: "Start"
                tasks: [{ id: "T1", type: "checkmark" }]
            }
            {
                id: "Q2"
                dependencies: ["Q1"]
                description: ["&7Kill it.", "{@pagebreak}", "Mátalo."]
                tasks: [{ id: "T2", type: "kill", entity: "mymod:boss", value: 1L }]
                rewards: [{ id: "R1", type: "item", item: "minecraft:diamond" }]
            }
        ]
    }""",
        "utf-8",
    )
    progress = tmp_path / "world/ftbquests"
    progress.mkdir(parents=True)
    (progress / "team.snbt").write_text('{name: "vasya#123", completed: { Q1: 1700L }}', "utf-8")
    return tmp_path


def test_load_quests_and_progress(server: Path):
    quests = {q.id: q for q in load_quests(server)}
    assert quests["Q1"].chapter == "Main Story"
    assert quests["Q1"].group == "Campaign"
    assert quests["Q2"].title == "mymod:boss"  # без названия — по цели задачи, как в FTB
    assert quests["Q2"].description == "Kill it."  # только первая (английская) страница
    assert quests["Q2"].tasks == ["убить mymod:boss"]
    assert quests["Q2"].rewards == ["minecraft:diamond"]
    teams = load_teams(server)
    assert teams[0].name == "vasya#123"
    assert [q.id for q in available(list(quests.values()), teams[0].completed)] == ["Q2"]


def test_available_respects_min_dependencies():
    def quest(qid: str, deps: list[str], need: int = 0) -> Quest:
        return Quest(qid, "c", "ch", "", qid, "", "", [], [], deps, need)

    quests = [quest("A", []), quest("B", []), quest("C", ["A", "B"]), quest("D", ["A", "B"], need=1)]
    assert [q.id for q in available(quests, {"A": 1})] == ["B", "D"]


def test_english_originals_attached(server: Path):
    original = server / "modpack-bridge/quests-original/quests/chapters"
    original.mkdir(parents=True)
    (original / "main.snbt").write_text(
        '{id: "C1", title: "Main Story", quests: [{id: "Q1", title: "Start", tasks: []}]}', "utf-8"
    )
    chapter = server / "config/ftbquests/quests/chapters/main.snbt"
    chapter.write_text(chapter.read_text("utf-8").replace('title: "Start"', 'title: "Начало"'), "utf-8")
    quests = {q.id: q for q in load_quests(server)}
    assert quests["Q1"].title == "Начало"
    assert quests["Q1"].title_en == "Start"
    assert quests["Q1"].chapter_en == "Main Story"
    assert quests["Q2"].title_en == ""
