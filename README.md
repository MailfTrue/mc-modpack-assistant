# Minecraft Modpack Support

ИИ-помощник по сборке **Prominence II: Hasturian Era** и мост между сервером Minecraft и Telegram.

- **`brain/`** — Python-сервис (uv): LLM-ядро на Claude Agent SDK (подписка Claude), Telegram-бот, WebSocket-мост для мода.
- **`mod/`** — серверный Fabric-мод (1.20.1): шлёт события сервера в brain. Игрокам ставить не нужно.

План и этапы — в [ROADMAP.md](ROADMAP.md).

## Что уже умеет

- `/ai <вопрос>` в Telegram, упоминание бота или reply на его ответ (продолжает разговор), скриншоты.
- ИИ ищет ответ в квестах, конфигах и датапаках сервера (только чтение) и в интернете.
- События сервера в Telegram: старт/стоп, вход/выход, смерти, достижения, игровой чат.

## Установка

### 1. Telegram-бот

1. В [@BotFather](https://t.me/BotFather): `/newbot` → получить токен.
2. Там же: `/setprivacy` → выбрать бота → **Disable** (иначе бот не видит обычные сообщения в группе).
3. Создать группу, добавить туда бота.

### 2. brain

Нужны [uv](https://docs.astral.sh/uv/) и залогиненный Claude Code (`claude login`) на этом ПК.

```powershell
cd brain
copy .env.example .env   # заполнить TELEGRAM_BOT_TOKEN и SERVER_DIR
uv run modpack-brain run
```

Написать в группе `/chatid`, вписать id в `ALLOWED_CHAT_IDS` в `.env`, перезапустить brain.

Проверить ИИ без Telegram:

```powershell
uv run modpack-brain ask "с чего начать в Prominence II?"
```

### 3. Мод

```powershell
cd mod
.\gradlew.bat build
```

Скопировать `mod/build/libs/modpack-bridge-<версия>.jar` в `mods/` **сервера** и перезапустить сервер.
При первом запуске мод создаёт `config/modpack-bridge.json` со случайным токеном — brain читает его оттуда сам.

Для сборки Gradle сам скачает JDK 25 в свой кэш (этого требует Fabric Loom); мод собирается под Java 17.

Отладка моста без Telegram: `uv run modpack-brain bridge` печатает события в консоль.

## Разработка

```powershell
cd brain
uv run pytest
uv run ruff check . ; uv run ruff format .

cd ..\mod
.\gradlew.bat build        # + тесты
.\gradlew.bat runServer    # тестовый сервер в mod/run (порт и конфиг — в mod/run)
```

## Безопасность

- Агенту доступны только чтение (`Read`/`Grep`/`Glob`) внутри папки сервера и веб-поиск; Bash и запись файлов выключены.
  Каждый вызов проверяется хуком `PreToolUse` (`brain/src/modpack_brain/llm.py`).
- Закрыты `server.properties`, конфиг моста с токеном, списки ops/whitelist/банов.
  Оговорка: широкий `Grep` по корню или `config/` теоретически может зацепить содержимое этих файлов.
  Мост слушает только `127.0.0.1`, так что токен снаружи бесполезен.
- Бот отвечает только в чатах из `ALLOWED_CHAT_IDS`; есть дневной лимит вопросов на человека.
