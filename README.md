# Minecraft Modpack Assistant

ИИ-помощник по сборке **Prominence II: Hasturian Era** и мост между сервером Minecraft и Telegram.

- **`mod/`** — серверный Fabric-мод (1.20.1). Запускает brain вместе с сервером и шлёт ему события сервера.
  Игрокам ставить не нужно.
- **`brain/`** — Python-сервис (uv): LLM-ядро на Claude Agent SDK (подписка Claude), Telegram-бот,
  WebSocket-мост для мода.

План и этапы — в [ROADMAP.md](ROADMAP.md).

## Что уже умеет

- `/ai <вопрос>` в Telegram, упоминание бота или reply на его ответ (продолжает разговор), скриншоты.
- ИИ ищет ответ в квестах, конфигах и датапаках сервера (только чтение) и в интернете.
- События сервера в Telegram: старт/стоп, вход/выход, смерти, достижения, игровой чат.

## Как это работает

```
сервер Minecraft ──запускает──► brain (uv run modpack-brain run --server-dir … --exit-on-stdin-eof)
   │ мод                           │
   └──── WebSocket 127.0.0.1 ─────►├─ Telegram-бот
                                   └─ Claude (подписка)
```

brain живёт ровно столько, сколько сервер: при остановке мод закрывает ему stdin и brain завершается;
если сервер упал — stdin закрывает ОС, и brain тоже выходит. Лог brain — `logs/modpack-brain.log` сервера.

## Установка

Нужны [uv](https://docs.astral.sh/uv/) и залогиненный Claude Code (`claude login`) на ПК с сервером.

1. **Telegram.** В [@BotFather](https://t.me/BotFather): `/newbot` → токен; `/setprivacy` → **Disable**.
   Создать группу и добавить туда бота.
2. **Мод.** `cd mod` → `.\gradlew.bat build` → скопировать `mod/build/libs/modpack-bridge-<версия>.jar`
   в `mods/` сервера. Для сборки Gradle сам скачает JDK 25 в свой кэш (этого требует Fabric Loom);
   мод собирается под Java 17.
3. **Запустить сервер один раз** — мод создаст `config/modpack-bridge.json`. Остановить и заполнить:

```jsonc
{
  "url": "ws://127.0.0.1:8765",
  "token": "…",                       // токен моста, генерируется сам
  "brain": {
    "autostart": true,
    "dir": "C:/путь/к/репозиторию/brain",
    "command": ["uv", "run", "modpack-brain", "run"]
  },
  "telegram": {
    "token": "123456:ABC…",           // от BotFather
    "allowedChatIds": [-100…],        // id группы: написать /chatid боту в группе
    "eventsChatId": null              // null — первый из allowedChatIds
  },
  "llm": { "model": "sonnet", "maxTurns": 30, "timeoutSeconds": 240, "questionsPerUserPerDay": 50 },
  "events": { "server": true, "joinLeave": true, "death": true, "advancement": true, "chat": true }
}
```

4. Запустить сервер. В группе появится «🟢 Сервер запущен».

## Обновление

`git pull` → пересобрать мод, если менялся `mod/` (и заменить jar на сервере) → перезапустить сервер.

## Запуск brain вручную

Нужен `brain/.env` с `SERVER_DIR` (см. `brain/.env.example`); остальные настройки берутся из конфига сервера.

```powershell
cd brain
uv run modpack-brain ask "с чего начать в Prominence II?"   # вопрос ИИ из консоли
uv run modpack-brain bridge                               # события от мода в консоль, без Telegram
```

`start-brain.bat` — запуск бота вручную, если в конфиге `brain.autostart: false`
(одновременно с автозапуском не нужен: два бота будут мешать друг другу).

## Разработка

```powershell
cd brain
uv run pytest
uv run ruff check . ; uv run ruff format .

cd ..\mod
.\gradlew.bat build        # + тесты
.\gradlew.bat runServer    # тестовый сервер в mod/run (свой конфиг в mod/run/config)
```

## Безопасность

- Агенту доступны только чтение (`Read`/`Grep`/`Glob`) внутри папки сервера и веб-поиск; Bash и запись выключены.
- Два слоя защиты файлов (`brain/src/modpack_brain/llm.py`): хук `PreToolUse` проверяет каждый вызов, а правила
  `permissions.deny` Claude Code вырезают закрытые файлы и из результатов широкого `Grep`.
  Закрыты `config/modpack-bridge.json` (токены), `server.properties`, списки ops/whitelist/банов, `*.env`.
- Мост слушает только `127.0.0.1` и проверяет токен.
- Бот отвечает только в чатах из `allowedChatIds`; есть дневной лимит вопросов на человека.
