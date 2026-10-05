import json
from pathlib import Path

from modpack_brain.config import Settings


def test_chat_ids_and_token_from_mod_config(tmp_path: Path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "modpack-bridge.json").write_text(json.dumps({"token": "abc"}), encoding="utf-8")
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "-100123, 42")
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    settings = Settings(_env_file=None)
    assert settings.allowed_chat_ids == [-100123, 42]
    assert settings.events_chat == -100123
    assert settings.resolve_bridge_token() == "abc"
