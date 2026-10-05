"""Разбор SNBT в варианте FTB Quests: ключи без кавычек, разделители — запятые или переводы строк,
числа с суффиксами (1L, 0.5d, 1b), типизированные массивы [I; 1, 2]."""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?[bBsSlLfFdD]?$")
_DELIMITERS = set(" \t\r\n,{}[]")


class SnbtError(ValueError):
    pass


def loads(text: str) -> Any:
    parser = _Parser(text)
    value = parser.value()
    parser.skip()
    if parser.pos != len(text):
        raise SnbtError(f"лишние данные на позиции {parser.pos}")
    return value


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n,":
            self.pos += 1

    def peek(self) -> str:
        self.skip()
        if self.pos >= len(self.text):
            raise SnbtError("неожиданный конец")
        return self.text[self.pos]

    def value(self) -> Any:
        char = self.peek()
        if char == "{":
            return self.compound()
        if char == "[":
            return self.list()
        if char in "\"'":
            return self.string()
        return self.bare()

    def compound(self) -> dict[str, Any]:
        self.pos += 1
        out: dict[str, Any] = {}
        while self.peek() != "}":
            key = self.string() if self.peek() in "\"'" else self.word(key=True)
            if self.peek() != ":":
                raise SnbtError(f"ожидалось ':' после ключа {key!r} на позиции {self.pos}")
            self.pos += 1
            out[key] = self.value()
        self.pos += 1
        return out

    def list(self) -> list[Any]:
        self.pos += 1
        # Типизированный массив: [I; 1, 2, 3]
        if re.match(r"[BIL];", self.text[self.pos : self.pos + 2]):
            self.pos += 2
        out = []
        while self.peek() != "]":
            out.append(self.value())
        self.pos += 1
        return out

    def string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        chars = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\" and self.pos + 1 < len(self.text):
                nxt = self.text[self.pos + 1]
                chars.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                self.pos += 2
                continue
            if char == quote:
                self.pos += 1
                return "".join(chars)
            chars.append(char)
            self.pos += 1
        raise SnbtError("незакрытая строка")

    def word(self, *, key: bool = False) -> str:
        # В ключе ':' — разделитель, в значении — часть слова (minecraft:stone).
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in _DELIMITERS:
            if key and self.text[self.pos] == ":":
                break
            self.pos += 1
        if start == self.pos:
            raise SnbtError(f"ожидалось значение на позиции {self.pos}")
        return self.text[start : self.pos]

    def bare(self) -> Any:
        token = self.word()
        if token in ("true", "false"):
            return token == "true"
        if _NUMBER.match(token):
            number = token.rstrip("bBsSlLfFdD") if token[-1].isalpha() else token
            is_float = any(c in number for c in ".eE") or token[-1] in "fFdD"
            return float(number) if is_float else int(number)
        return token
