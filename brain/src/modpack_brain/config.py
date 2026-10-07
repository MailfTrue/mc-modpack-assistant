"""Настройки сервиса.

Основной источник — конфиг мода на сервере `SERVER_DIR/config/modpack-bridge.json` (один файл на всё).
Переменные окружения и `brain/.env` его переопределяют (удобно для разработки).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# brain/.env, независимо от того, откуда запущен процесс.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Конфиг мода на сервере; мод создаёт его (с токеном моста) при первом запуске.
MOD_CONFIG = Path("config") / "modpack-bridge.json"


def read_server_config(server_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((server_dir / MOD_CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def map_server_config(data: dict[str, Any]) -> dict[str, Any]:
    """Поля конфига мода → поля Settings. Пустые значения пропускаем, чтобы работали умолчания."""
    telegram = data.get("telegram") or {}
    llm = data.get("llm") or {}
    status = telegram.get("status") or {}
    out: dict[str, Any] = {
        "telegram_bot_token": telegram.get("token"),
        "allowed_chat_ids": telegram.get("allowedChatIds"),
        "events_chat_id": telegram.get("eventsChatId"),
        "status_pinned": status.get("pinned"),
        "status_address": status.get("address"),
        "status_panel_url": status.get("panelUrl"),
        "pack_name": llm.get("packName"),
        "pack_notes": llm.get("packNotes"),
        "llm_model": llm.get("model"),
        "llm_max_turns": llm.get("maxTurns"),
        "llm_timeout_seconds": llm.get("timeoutSeconds"),
        "questions_per_user_per_day": llm.get("questionsPerUserPerDay"),
    }
    if isinstance(url := data.get("url"), str) and url:
        parts = urlsplit(url)
        out["bridge_host"] = parts.hostname
        out["bridge_port"] = parts.port
    return {key: value for key, value in out.items() if value not in (None, "", [])}


class ServerConfigSource(PydanticBaseSettingsSource):
    """Источник настроек из конфига мода; папку сервера берёт из уже прочитанных env/.env."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        server_dir = self.current_state.get("server_dir") or os.environ.get("SERVER_DIR")
        if not server_dir:
            server_dir = dotenv_values(ENV_FILE).get("SERVER_DIR") if ENV_FILE.exists() else None
        if not server_dir:
            return {}
        return map_server_config(read_server_config(Path(server_dir).expanduser()))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: SecretStr | None = None
    allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    events_chat_id: int | None = None
    # Закреплённое сообщение со статусом сервера в чате событий
    status_pinned: bool = True
    status_address: str = ""
    status_panel_url: str = ""

    # Сервер Minecraft
    server_dir: Path

    # Сборка (для промпта; версию игры и число модов brain узнаёт из выгрузки)
    pack_name: str = ""
    pack_notes: str = ""

    # LLM
    llm_model: str = "sonnet"
    llm_max_turns: int = 30
    llm_timeout_seconds: float = 240.0
    questions_per_user_per_day: int = 50

    # Мост с модом
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8765
    bridge_token: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, dotenv_settings, ServerConfigSource(settings_cls)

    @field_validator("allowed_chat_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @field_validator("server_dir")
    @classmethod
    def _server_dir_exists(cls, value: Path) -> Path:
        value = value.expanduser().resolve()
        if not value.is_dir():
            raise ValueError(f"папка сервера не найдена: {value}")
        return value

    @property
    def events_chat(self) -> int | None:
        """Куда слать события сервера: явно заданный чат или первый разрешённый."""
        if self.events_chat_id is not None:
            return self.events_chat_id
        return self.allowed_chat_ids[0] if self.allowed_chat_ids else None

    def resolve_bridge_token(self) -> str | None:
        """Токен из env/.env, иначе из конфига мода (читается каждый раз: мод создаёт его при первом запуске)."""
        if self.bridge_token is not None:
            return self.bridge_token.get_secret_value()
        token = read_server_config(self.server_dir).get("token")
        return token if isinstance(token, str) and token else None
