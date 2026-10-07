import itertools

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from modpack_brain.telegram import status as status_module
from modpack_brain.telegram.status import ServerState, StatusBoard, keyboard, render


def test_render_online_with_players():
    text = render(ServerState("online", ["zed", "Alice"], 20), pack="Pack <1>", address="mc.example.com")
    assert text.splitlines() == [
        "🟢 <b>Сервер онлайн</b>",
        "👥 Игроки 2/20: Alice, zed",
        "🌐 Адрес: <code>mc.example.com</code>",
        "🧩 Pack &lt;1&gt;",
    ]


def test_render_online_empty_and_other_phases():
    assert "👥 Игроки 0/20 — никого" in render(ServerState("online", [], 20))
    assert render(ServerState("offline")) == "🔴 <b>Сервер выключен</b>"
    assert render(ServerState("starting")) == "🟡 <b>Сервер запускается…</b>"


def test_keyboard_only_with_url():
    assert keyboard("") is None
    button = keyboard("https://example.com").inline_keyboard[0][0]
    assert (button.text, button.url) == ("Открыть панель", "https://example.com")


class FakeBot:
    ids = itertools.count(500)

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edited: list[tuple[int, str]] = []
        self.pinned: list[int] = []
        self.missing: set[int] = set()

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return type("Message", (), {"message_id": next(self.ids)})()

    async def edit_message_text(self, text, *, chat_id, message_id, **kwargs):
        if message_id in self.missing:
            method = EditMessageText(text=text, chat_id=chat_id, message_id=message_id)
            raise TelegramBadRequest(method, "Bad Request: message to edit not found")
        self.edited.append((message_id, text))

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        self.pinned.append(message_id)


class FakeBridge:
    connected = True

    def __init__(self, players: list[str]) -> None:
        self.players = players

    async def request(self, method, timeout=5.0, **params):
        assert method == "online"
        return {"players": self.players, "max": 10}


async def test_posts_pins_once_then_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(status_module, "EVENT_DELAY_SECONDS", 0)
    bot = FakeBot()
    board = StatusBoard(bot, -1, tmp_path)
    board.bridge = FakeBridge(["Steve"])
    await board.start()
    assert len(bot.sent) == 1 and "запускается" in bot.sent[0]
    assert len(bot.pinned) == 1
    message_id = bot.pinned[0]

    await board.on_event({"event": "server_started"})
    assert bot.edited[-1] == (message_id, render(ServerState("online", ["Steve"], 10)))

    await board.on_event({"event": "server_stopping"})
    assert "выключен" in bot.edited[-1][1]
    await board.stop(offline=True)
    assert len(bot.sent) == 1  # без новых сообщений: только правки

    # После перезапуска brain правит то же сообщение, а не шлёт новое.
    again = StatusBoard(bot, -1, tmp_path)
    await again.start()
    assert len(bot.sent) == 1
    assert bot.edited[-1][0] == message_id
    await again.stop(offline=False)


async def test_reposts_when_message_deleted(tmp_path):
    bot = FakeBot()
    board = StatusBoard(bot, -1, tmp_path)
    await board.start()
    await board.stop(offline=False)
    bot.missing.add(bot.pinned[0])

    again = StatusBoard(bot, -1, tmp_path)
    await again.start()
    assert len(bot.sent) == 2 and len(bot.pinned) == 2
    await again.stop(offline=False)


async def test_unchanged_text_is_not_resent(tmp_path):
    bot = FakeBot()
    board = StatusBoard(bot, -1, tmp_path)
    board.bridge = FakeBridge([])
    await board.start()
    await board.on_event({"event": "server_started"})
    edits = len(bot.edited)
    await board.refresh()
    assert len(bot.edited) == edits
    await board.stop(offline=False)
