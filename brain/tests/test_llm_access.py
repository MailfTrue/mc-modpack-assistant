from pathlib import Path

import pytest

from modpack_brain.llm import check_tool_access


@pytest.fixture
def server(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    return tmp_path.resolve()


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": "config/ftbquests/quests/chapters/main_story.snbt"}),
        ("Grep", {"pattern": "netherite", "path": "config"}),
        ("Grep", {"pattern": "netherite"}),
        ("Glob", {"pattern": "mods/*.jar"}),
    ],
)
def test_allowed(server: Path, tool: str, tool_input: dict):
    assert check_tool_access(server, tool, tool_input) is None


def test_absolute_path_inside_server_allowed(server: Path):
    assert check_tool_access(server, "Read", {"file_path": str(server / "config" / "a.json")}) is None


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Bash", {"command": "dir"}),
        ("Write", {"file_path": "x.txt", "content": ""}),
        ("Read", {"file_path": "../secret.txt"}),
        ("Read", {"file_path": "C:/Users/1/.claude/.credentials.json"}),
        ("Read", {"file_path": "server.properties"}),
        ("Read", {"file_path": "config/modpack-bridge.json"}),
        ("Read", {"file_path": "config/../server.properties"}),
        ("Read", {"file_path": "brain/.env"}),
        ("Grep", {"pattern": "x", "path": "C:/Windows"}),
        ("Grep", {"pattern": "x", "glob": "../**"}),
        ("Glob", {"pattern": "../../**/*.json"}),
        ("Glob", {"pattern": "C:/Users/**"}),
        ("Glob", {"pattern": "*.jar", "path": ".."}),
    ],
)
def test_denied(server: Path, tool: str, tool_input: dict):
    assert check_tool_access(server, tool, tool_input) is not None


def test_web_allowed(server: Path):
    assert check_tool_access(server, "WebSearch", {"query": "prominence 2"}) is None


@pytest.mark.parametrize("pattern", ["*.properties", "server.*", "config/modpack-*.json"])
def test_glob_patterns_hitting_denied_files(server: Path, pattern: str):
    assert check_tool_access(server, "Glob", {"pattern": pattern}) is not None
    assert check_tool_access(server, "Grep", {"pattern": "x", "glob": pattern}) is not None
