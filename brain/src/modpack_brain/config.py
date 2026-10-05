"""Настройки сервиса: переменные окружения и файл `.env`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# brain/.env, независимо от того, откуда запущен процесс.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Файл конфига мода на сервере; мод сам генерирует в нём токен моста при первом запуске.
MOD_CONFIG = Path("config") / "modpack-bridge.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: SecretStr | None = None
    allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    events_chat_id: int | None = None

    # Сервер Minecraft
    server_dir: Path

    # LLM
    llm_model: str = "sonnet"
    llm_max_turns: int = 30
    llm_timeout_seconds: float = 240.0
    questions_per_user_per_day: int = 50

    # Мост с модом
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8765
    bridge_token: SecretStr | None = None

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
        """Токен из .env, иначе тот, что мод записал в свой конфиг на сервере."""
        if self.bridge_token is not None:
            return self.bridge_token.get_secret_value()
        path = self.server_dir / MOD_CONFIG
        try:
            token = json.loads(path.read_text(encoding="utf-8")).get("token")
        except (OSError, ValueError):
            return None
        return token if isinstance(token, str) and token else None
