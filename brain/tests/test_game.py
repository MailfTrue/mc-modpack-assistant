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

    async def mirror(player, question, answer):
        mirrored.append((player, question, answer))

    assistant = FakeAssistant()
    game = GameAi(assistant, send, mirror, daily_limit=5)
    await game.handle({"id": "q1", "player": "Vasya", "uuid": "u1", "question": "привет"})
    await game.handle({"id": "q2", "player": "Vasya", "uuid": "u1", "question": "а ещё?"})
    assert sent == [
        {"type": "ai_answer", "id": "q1", "text": "ответ 1"},
        {"type": "ai_answer", "id": "q2", "text": "ответ 2"},
    ]
    assert mirrored[0] == ("Vasya", "привет", "ответ 1")
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
