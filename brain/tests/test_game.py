from modpack_brain.game import GameAi, build_prompt
from modpack_brain.llm import Answer


class FakeAssistant:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ask(self, question, *, system_prompt, images=None, session_id=None):
        self.calls.append({"question": question, "session_id": session_id})
        return Answer(f"ответ {len(self.calls)}", session_id=f"s{len(self.calls)}")


def test_prompt_contains_context():
    prompt = build_prompt("Vasya", "что это?", {"main_hand": {"id": "minecraft:diamond"}})
    assert "Vasya" in prompt and "minecraft:diamond" in prompt


async def test_answer_sent_mirrored_and_session_continues():
    sent, mirrored = [], []

    async def send(message):
        sent.append(message)
        return True

    async def mirror(player, question, answer, session_id):
        mirrored.append((player, question, answer, session_id))

    assistant = FakeAssistant()
    game = GameAi(assistant, send, mirror, daily_limit=5)
    await game.handle({"id": "q1", "player": "Vasya", "uuid": "u1", "question": "привет"})
    await game.handle({"id": "q2", "player": "Vasya", "uuid": "u1", "question": "а ещё?"})
    assert sent == [
        {"type": "ai_answer", "id": "q1", "text": "ответ 1"},
        {"type": "ai_answer", "id": "q2", "text": "ответ 2"},
    ]
    assert mirrored[0] == ("Vasya", "привет", "ответ 1", "s1")
    assert assistant.calls[1]["session_id"] == "s1"


async def test_daily_limit():
    sent = []

    async def send(message):
        sent.append(message)
        return True

    game = GameAi(FakeAssistant(), send, None, daily_limit=1)
    await game.handle({"id": "a", "player": "P", "uuid": "u", "question": "1"})
    await game.handle({"id": "b", "player": "P", "uuid": "u", "question": "2"})
    assert "лимит" in sent[1]["text"]


def test_eval_check():
    from modpack_brain.eval import check

    assert check("Нужен Iron Ingot", ["mcp__pack__item_recipes"], ["iron"], ["item_recipes"]) == []
    assert check("ничего", [], ["iron"], ["item_recipes"]) == [
        "в ответе нет ни одного из: iron",
        "не вызван item_recipes",
    ]


async def test_continue_specific_answer_by_another_player():
    sent = []

    async def send(message):
        sent.append(message)
        return True

    assistant = FakeAssistant()
    game = GameAi(assistant, send, None, daily_limit=10)
    await game.handle({"id": "a1", "player": "Vasya", "uuid": "u1", "question": "первый"})
    await game.handle({"id": "b1", "player": "Petya", "uuid": "u2", "question": "уточню", "continue": "a1"})
    assert assistant.calls[1]["session_id"] == "s1"  # Петя продолжил разговор Васи
    await game.handle({"id": "c1", "player": "Petya", "uuid": "u2", "question": "?", "continue": "zzz"})
    assert "не помню" in sent[-1]["text"]


def test_clip_for_game():
    from modpack_brain.game import clip_for_game

    short = "коротко"
    assert clip_for_game(short, mirrored=True) == short
    long = "\n\n".join(f"Абзац {i}: " + "слово " * 30 for i in range(20))
    clipped = clip_for_game(long, mirrored=True, limit=500)
    assert len(clipped) < 560
    assert clipped.endswith("…(полный ответ — в Telegram)")
    assert "Абзац 0" in clipped


async def test_inventory_attached_to_game_question():
    async def send(message):
        return True

    async def inventory(player):
        return f"Инвентарь {player}: 3× Iron Ingot"

    assistant = FakeAssistant()
    game = GameAi(assistant, send, None, daily_limit=5, inventory=inventory)
    await game.handle({"id": "q", "player": "Steve", "uuid": "u", "question": "хватит на кирку?"})
    assert "Инвентарь Steve: 3× Iron Ingot" in assistant.calls[0]["question"]
