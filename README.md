# Minecraft Modpack Assistant

ИИ-помощник по модпаку и мост между сервером Minecraft (Fabric) и Telegram.
Под конкретную сборку ничего не зашито: название и заметки о ней задаются в конфиге сервера
(`llm.packName`, `llm.packNotes`), версию игры и список модов бот узнаёт сам из выгрузки мода.

- **`mod/`** — серверный Fabric-мод (1.20.1). Запускает brain вместе с сервером и шлёт ему события сервера.
  Игрокам ставить не нужно.
- **`brain/`** — Python-сервис (uv): LLM-ядро на Claude Agent SDK (подписка Claude), Telegram-бот,
  WebSocket-мост для мода.

План и этапы — в [ROADMAP.md](ROADMAP.md).

## Что уже умеет

- **Telegram:** `/ai <вопрос>`, упоминание бота или reply на его ответ (продолжает разговор), скриншоты.
  `/online` — кто на сервере.
- **В игре:** `/ai <вопрос>` — ИИ видит, что у игрока в руках, на какой блок он смотрит, где он; ответ видят все,
  предметы в ответе показывают игровую подсказку при наведении. Повторный `/ai` в течение 15 минут продолжает разговор.
- **Мост чата:** игровой чат → Telegram и сообщения группы → игра (`[TG] Имя: текст`).
- **События сервера в Telegram:** старт/стоп, вход/выход, смерти, достижения; вопросы `/ai` из игры дублируются.
- **Закреп со статусом:** бот держит в чате событий одно закреплённое сообщение — онлайн/выключен, кто играет,
  адрес и кнопка «Открыть панель»; правит его при входе/выходе, старте/остановке (и краше) сервера.
- **Знания о сборке:** мод при старте сервера выгружает итоговые предметы, теги и рецепты (с датапаками и
  изменениями сборки), brain строит из них SQLite-индекс с русскими названиями, квестами FTB и прогрессом команд.
  У ИИ инструменты `find_item`, `item_recipes`, `search_quests`, `team_progress`, `tag_items`, `list_mods`;
  плюс файлы сервера (только чтение) и интернет.

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
    "eventsChatId": null,             // null — первый из allowedChatIds
    "status": {                       // закреплённое сообщение со статусом (боту нужно право закреплять)
      "pinned": true,
      "address": "mc.example.com",    // адрес для подключения
      "panelUrl": "https://…"         // кнопка «Открыть панель»; пусто — без кнопки
    }
  },
  "llm": {
    "packName": "Название сборки",      // для ИИ и справки бота; пусто — «модпак»
    "packNotes": "RPG, квесты FTB…",    // что ИИ стоит знать о сборке (свободный текст)
    "model": "sonnet", "maxTurns": 30, "timeoutSeconds": 240, "questionsPerUserPerDay": 50
  },
  "events": { "server": true, "joinLeave": true, "death": true, "advancement": true, "chat": true }
}
```

4. Запустить сервер. В группе появится «🟢 Сервер запущен».

## Переведённые квесты

Если у сборки есть русская локализация, которая переводит файлы квестов FTB (книгу квестов задаёт сервер,
поэтому переведённые `config/ftbquests` копируются с клиента на сервер), положите английские оригиналы в
`<сервер>/modpack-bridge/quests-original/quests` — индекс ИИ будет искать по обоим языкам, а промпт сам учтёт,
что квесты переведены.

## Эталонные вопросы

`uv run modpack-brain eval` берёт вопросы из `<сервер>/modpack-bridge/eval/questions.toml` (под свою сборку),
а если их нет — общий пример `brain/eval/questions.example.toml`.

После обновления сборки: обновить локализацию на клиенте, запустить игру, снова скопировать эти две папки
на сервер, а свежие английские оригиналы (`config/ftbquests/quests` из сборки до перевода) — в `quests-original`.

## Обновление

Вручную: `git pull` → пересобрать мод, если менялся `mod/` (и заменить jar на сервере) → перезапустить сервер.

Сервер на Linux с доступом по ssh — одной командой из Git Bash (мод собирается локально, на сервере не нужен JDK):

```bash
cp deploy/deploy.env.example deploy/deploy.env   # один раз: DEPLOY_SSH=user@host
deploy/deploy.sh                 # перезапуск с предупреждением игрокам за 60 с
deploy/deploy.sh --when-empty    # дождаться, пока все выйдут (или --now, --no-restart)
```

`deploy.sh` прогоняет тесты brain и мода, делает `git push`, для новой `mod_version` создаёт GitHub Release
`v<версия>` с jar (нужен [GitHub CLI](https://cli.github.com/) и один раз `gh auth login`; поменял код мода —
подними версию, иначе скрипт остановится) и запускает на сервере `deploy/mc-update`: `git pull` + `uv sync`,
jar из последнего релиза со сверкой SHA-256 (старый — в `mods-backup/`). Изменился только brain —
перезапускается только он (мод поднимает его сам), сервер не трогается. Поменялись `deploy/server` или
`deploy/status` — `mc-update` применяет их сам (Minecraft при этом не перезапускается). `deploy/mc` — консоль
через RCON: `mc list`, `mc say …`.

## Свой сервер (Ubuntu)

`deploy/server/setup-server.sh` настраивает чистую Ubuntu 24.04 и приводит уже настроенную к тому, что описано
в репозитории (идемпотентно; сервер Minecraft никогда не перезапускает):

- Java 17, uv, Claude Code, клон репозитория в `~/mc-modpack-assistant`, swap 4 ГБ;
- служба `minecraft` (`~/bin/mc-start`: память, флаги G1, UTF-8), автозапуск при загрузке, перезапуск при падении;
- `needrestart` не перезапускает сервер после автообновлений Ubuntu;
- страница статуса (`deploy/status`, служба `mc-status` на `127.0.0.1:8080`): онлайн, игроки, адрес, сборка;
  название и описание — из MOTD, адрес — `telegram.status.address`;
- Traefik перед ней: HTTPS с Let's Encrypt для `--domain` (A-запись домена → IP сервера), по голому IP — http;
- ufw: открыты только 22, 80, 443, 25565 (RCON — только локально).

```bash
# первый раз, от пользователя с sudo:
ssh user@host 'bash -s -- --domain mc.example.com --memory 7G' < deploy/server/setup-server.sh
# потом (параметры запомнены в ~/.config/minecraft-host.env):
~/mc-modpack-assistant/deploy/server/setup-server.sh
```

Затем скопировать сервер в `~/server` и положить секреты (скрипт напомнит, чего не хватает):
токен Claude — `claude setup-token` на своём ПК → `CLAUDE_CODE_OAUTH_TOKEN=…` в `~/.config/minecraft.env`
(chmod 600); в `server.properties` — `enable-rcon=true` и случайный `rcon.password`; в
`config/modpack-bridge.json` — `brain.dir` (`/home/<user>/mc-modpack-assistant/brain`) и токен Telegram.
Запуск: `sudo systemctl start minecraft`.

## Запуск brain вручную

Нужен `brain/.env` с `SERVER_DIR` (см. `brain/.env.example`); остальные настройки берутся из конфига сервера.

```powershell
cd brain
uv run modpack-brain ask "с чего начать в этой сборке?"     # вопрос ИИ из консоли
uv run modpack-brain index [--force]                      # пересобрать индекс из выгрузки (обычно сам)
uv run modpack-brain eval [id ...]                        # эталонные вопросы → eval/reports/*.md
uv run modpack-brain bridge                               # мост без Telegram: события и ответы /ai в консоль;
                                                          # ввод: /online или текст → в игровой чат
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
