"""Markdown от LLM → HTML-разметка Telegram, плюс нарезка длинных ответов."""

from __future__ import annotations

import html
import re

TELEGRAM_LIMIT = 4096
# Запас под теги, которые добавляются при конвертации.
CHUNK_SOURCE_LIMIT = 3500

_FENCE = re.compile(r"^```")
_ITEM = re.compile(r"\[\[#?([a-z0-9_.-]+):([a-z0-9_./-]+)\]\]")
_CODE_BLOCK = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def to_telegram_html(markdown: str) -> str:
    """Упрощённая конвертация: Telegram понимает только b/i/s/code/pre/a/blockquote."""
    blocks: list[str] = []

    def stash_block(match: re.Match[str]) -> str:
        blocks.append(f"<pre>{html.escape(match.group(1).rstrip(), quote=False)}</pre>")
        return f"\x00B{len(blocks) - 1}\x00"

    # Маркеры предметов для игры ([[minecraft:iron_ingot]]) → «Iron Ingot».
    markdown = _ITEM.sub(lambda m: m.group(2).rsplit("/", 1)[-1].replace("_", " ").title(), markdown)
    text = _CODE_BLOCK.sub(stash_block, markdown.strip())
    out: list[str] = []
    quote: list[str] = []

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>" + "\n".join(quote) + "</blockquote>")
            quote.clear()

    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            quote.append(_inline(line.lstrip()[1:].lstrip()))
            continue
        flush_quote()
        if _RULE.match(line) or _TABLE_SEPARATOR.match(line):
            continue
        if header := _HEADER.match(line):
            out.append(f"<b>{_inline(header.group(1))}</b>")
            continue
        if bullet := _BULLET.match(line):
            line = bullet.group(1) + "• " + line[bullet.end() :]
        out.append(_inline(line))
    flush_quote()

    result = "\n".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return re.sub(r"\x00B(\d+)\x00", lambda m: blocks[int(m.group(1))], result)


def _inline(text: str) -> str:
    codes: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(match.group(1), quote=False)}</code>")
        return f"\x00C{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(stash_code, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    return re.sub(r"\x00C(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def split_markdown(markdown: str, limit: int = CHUNK_SOURCE_LIMIT) -> list[str]:
    """Режет по абзацам и строкам, не разрывая блоки кода (кроме слишком длинных)."""
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    in_code = False
    fence = "```"

    def flush() -> None:
        nonlocal size
        if current:
            chunk = "\n".join(current)
            if in_code:
                chunk += "\n```"
            if chunk.strip():
                pieces.append(chunk.strip("\n"))
            current.clear()
            size = 0

    for line in markdown.strip().split("\n"):
        while len(line) > limit:
            flush()
            head, line = line[:limit], line[limit:]
            pieces.append(head)
        if size + len(line) + 1 > limit:
            reopen = in_code
            flush()
            if reopen:
                current.append(fence)
                size = len(fence) + 1
        if _FENCE.match(line.strip()):
            if not in_code:
                fence = line.strip()
            in_code = not in_code
        current.append(line)
        size += len(line) + 1
    in_code = False
    flush()
    return pieces


def render(markdown: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Готовые к отправке HTML-сообщения, каждое гарантированно не длиннее лимита Telegram.

    После конвертации текст растёт (экранирование &lt;, теги), поэтому кусок, не влезший в лимит,
    режем мельче и конвертируем заново.
    """
    out: list[str] = []
    for chunk in split_markdown(markdown):
        out += _render_chunk(chunk, limit)
    return out


def _render_chunk(chunk: str, limit: int) -> list[str]:
    html_text = to_telegram_html(chunk)
    if len(html_text) <= limit:
        return [html_text] if html_text.strip() else []
    smaller = split_markdown(chunk, limit=max(len(chunk) // 2, 1))
    if len(smaller) <= 1:
        # Один неделимый кусок (например, одна очень длинная строка) — режем «в лоб» как обычный текст.
        return [html.escape(part, quote=False) for part in split_plain(chunk, limit // 5)]
    return [part for piece in smaller for part in _render_chunk(piece, limit)]


def split_plain(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Простой текст на куски не длиннее limit — по строкам, длинные строки — жёстко."""
    pieces: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current.strip():
        pieces.append(current)
    return [p for p in pieces if p.strip()]
