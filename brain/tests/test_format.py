from modpack_brain.telegram.format import TELEGRAM_LIMIT, render, split_markdown, to_telegram_html


def test_inline_markup():
    html = to_telegram_html("**Жирный** и *курсив*, `код <x>` и [вики](https://wiki.example/a_b)")
    assert html == (
        '<b>Жирный</b> и <i>курсив</i>, <code>код &lt;x&gt;</code> и <a href="https://wiki.example/a_b">вики</a>'
    )


def test_snake_case_is_not_italic():
    assert to_telegram_html("предмет minecraft:iron_ingot_block") == "предмет minecraft:iron_ingot_block"


def test_headers_lists_quotes_and_code_blocks():
    html = to_telegram_html("## Рецепт\n- первое\n* второе\n> цитата\n\n```\na < b\n```")
    assert html == "<b>Рецепт</b>\n• первое\n• второе\n<blockquote>цитата</blockquote>\n\n<pre>a &lt; b</pre>"


def test_html_is_escaped():
    assert to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_table_separator_dropped():
    assert to_telegram_html("| a | b |\n|---|---|\n| 1 | 2 |") == "| a | b |\n| 1 | 2 |"


def test_split_respects_limit_and_code_fences():
    text = "\n\n".join(f"абзац {i} " + "слово " * 50 for i in range(40)) + "\n```\n" + "x = 1\n" * 900 + "```"
    chunks = split_markdown(text, limit=1000)
    assert len(chunks) > 5
    assert all(len(c) <= 1000 + 10 for c in chunks)
    assert all(c.count("```") % 2 == 0 for c in chunks)


def test_render_fits_telegram():
    text = "строка с **жирным** текстом\n" * 1000
    assert all(len(m) <= TELEGRAM_LIMIT for m in render(text))


def test_long_line_split():
    assert all(len(c) <= 100 for c in split_markdown("a" * 450, limit=100))
