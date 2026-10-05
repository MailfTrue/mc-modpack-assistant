from modpack_brain.events import format_event


def test_join_escapes_name():
    assert format_event({"event": "join", "player": "<Vasya>"}) == "➕ <b>&lt;Vasya&gt;</b> зашёл на сервер"


def test_death_uses_game_message():
    assert format_event({"event": "death", "player": "Vasya", "message": "Vasya was slain by Zombie"}) == (
        "💀 Vasya was slain by Zombie"
    )


def test_advancement():
    text = format_event(
        {
            "event": "advancement",
            "player": "Vasya",
            "title": "Diamonds!",
            "description": "Acquire diamonds",
            "frame": "task",
        }
    )
    assert text == "🏅 <b>Vasya</b> получил достижение <b>[Diamonds!]</b>\n<i>Acquire diamonds</i>"


def test_empty_chat_and_unknown_skipped():
    assert format_event({"event": "chat", "player": "Vasya", "message": "  "}) is None
    assert format_event({"event": "something"}) is None
