import json
from pathlib import Path

import pytest

from modpack_brain.config import Settings, map_server_config

SERVER_CONFIG = {
    "url": "ws://127.0.0.1:9100",
    "token": "abc",
    "brain": {"autostart": True, "dir": "C:/repo/brain"},
    "telegram": {"token": "123:tg", "allowedChatIds": [-100123, 42], "eventsChatId": None},
    "llm": {"model": "opus", "maxTurns": 10, "timeoutSeconds": 60, "questionsPerUserPerDay": 5},
}


@pytest.fixture
def server(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "modpack-bridge.json").write_text(json.dumps(SERVER_CONFIG), encoding="utf-8")
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_CHAT_IDS", "LLM_MODEL", "BRIDGE_TOKEN", "BRIDGE_PORT"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_map_skips_empty_values():
    mapped = map_server_config({"telegram": {"token": "", "allowedChatIds": []}, "llm": {"model": "haiku"}})
    assert mapped == {"llm_model": "haiku"}


def test_settings_from_server_config(server: Path):
    settings = Settings(_env_file=None)
    assert settings.telegram_bot_token.get_secret_value() == "123:tg"
    assert settings.allowed_chat_ids == [-100123, 42]
    assert settings.events_chat == -100123
    assert settings.llm_model == "opus"
    assert settings.llm_max_turns == 10
    assert settings.questions_per_user_per_day == 5
    assert (settings.bridge_host, settings.bridge_port) == ("127.0.0.1", 9100)
    assert settings.resolve_bridge_token() == "abc"


def test_env_overrides_server_config(server: Path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "haiku")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "7, 8")
    monkeypatch.setenv("BRIDGE_TOKEN", "from-env")
    settings = Settings(_env_file=None)
    assert settings.llm_model == "haiku"
    assert settings.allowed_chat_ids == [7, 8]
    assert settings.resolve_bridge_token() == "from-env"


def test_token_appears_after_mod_creates_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    settings = Settings(_env_file=None)
    assert settings.resolve_bridge_token() is None
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "modpack-bridge.json").write_text('{"token": "later"}', encoding="utf-8")
    assert settings.resolve_bridge_token() == "later"
