"""Прогон эталонных вопросов (eval/questions.toml) и отчёт в eval/reports/ для ручной проверки."""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import prompts
from .llm import Assistant

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
TOOL_PREFIX = "mcp__pack__"


@dataclass
class Result:
    id: str
    question: str
    answer: str
    tools: list[str]
    seconds: float
    problems: list[str]


def check(answer: str, tools: list[str], expect: list[str], need_tools: list[str]) -> list[str]:
    problems = []
    if expect and not any(word.lower() in answer.lower() for word in expect):
        problems.append(f"в ответе нет ни одного из: {', '.join(expect)}")
    used = {t.removeprefix(TOOL_PREFIX) for t in tools}
    problems += [f"не вызван {tool}" for tool in need_tools if tool not in used]
    return problems


async def run_eval(assistant: Assistant, only: list[str] | None = None) -> Path:
    data = tomllib.loads((EVAL_DIR / "questions.toml").read_text(encoding="utf-8"))
    results = []
    for item in data["question"]:
        if only and item["id"] not in only:
            continue
        started = time.monotonic()
        answer = await assistant.ask(item["text"], system_prompt=prompts.TELEGRAM)
        seconds = time.monotonic() - started
        problems = check(answer.text, answer.tools_used, item.get("expect", []), item.get("tools", []))
        if not answer.ok:
            problems.insert(0, "ошибка ответа")
        results.append(Result(item["id"], item["text"], answer.text, answer.tools_used, seconds, problems))
        print(f"{'OK  ' if not problems else 'FAIL'} {item['id']} ({seconds:.0f} с) {'; '.join(problems)}", flush=True)
    return _report(results)


def _report(results: list[Result]) -> Path:
    passed = sum(1 for r in results if not r.problems)
    lines = [
        f"# Eval {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Прошло автопроверку: **{passed}/{len(results)}**, "
        f"среднее время {sum(r.seconds for r in results) / max(len(results), 1):.0f} с.",
        "",
    ]
    for r in results:
        status = "✅" if not r.problems else "❌ " + "; ".join(r.problems)
        tools = ", ".join(t.removeprefix(TOOL_PREFIX) for t in r.tools) or "нет"
        lines += [
            f"## {r.id} — {status}",
            "",
            f"**Вопрос:** {r.question}",
            "",
            f"_Инструменты: {tools}; {r.seconds:.0f} с_",
        ]
        lines += ["", r.answer, ""]
    out = EVAL_DIR / "reports" / f"{datetime.now():%Y%m%d-%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
