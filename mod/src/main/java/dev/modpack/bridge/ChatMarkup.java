package dev.modpack.bridge;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Упрощённый markdown от LLM → куски текста со стилями (без зависимостей от Minecraft, чтобы тестировать).
 * Поддерживается: **жирный**, *курсив*, `код`, [текст](https://…), [[ns:id]] — предмет, заголовки, списки, цитаты.
 */
public final class ChatMarkup {
	public record Span(String text, boolean bold, boolean italic, boolean code, String link, String itemId) {
		static Span plain(String text, boolean bold, boolean italic) {
			return new Span(text, bold, italic, false, null, null);
		}
	}

	private static final Pattern INLINE = Pattern.compile(
			"`([^`\\n]+)`"                                              // 1 код
					+ "|\\[\\[#?([a-z0-9_.-]+:[a-z0-9_./-]+)]]"         // 2 предмет
					+ "|\\[([^\\]\\n]+)]\\((https?://[^\\s)]+)\\)"      // 3,4 ссылка
					+ "|\\*\\*(.+?)\\*\\*"                              // 5 жирный
					+ "|(?<![\\w*])\\*(?!\\s)([^*\\n]+?)(?<!\\s)\\*(?![\\w*])"); // 6 курсив
	private static final Pattern HEADER = Pattern.compile("^\\s{0,3}#{1,6}\\s+(.*?)\\s*#*\\s*$");
	private static final Pattern BULLET = Pattern.compile("^(\\s*)[-*+]\\s+");
	private static final Pattern RULE = Pattern.compile("^\\s*([-*_])(\\s*\\1){2,}\\s*$");
	private static final Pattern TABLE_SEPARATOR = Pattern.compile("^\\s*\\|?[\\s:|-]+\\|[\\s:|-]*$");
	private static final Pattern FENCE = Pattern.compile("^\\s*```.*$");

	private ChatMarkup() {
	}

	public static List<Span> parse(String markdown) {
		List<Span> out = new ArrayList<>();
		String[] lines = markdown.strip().replace("\r", "").split("\n");
		boolean first = true;
		boolean blank = false;
		for (String line : lines) {
			if (FENCE.matcher(line).matches() || RULE.matcher(line).matches() || TABLE_SEPARATOR.matcher(line).matches()) {
				continue;
			}
			// Схлопываем подряд идущие пустые строки: место в чате дорого.
			if (line.isBlank()) {
				blank = true;
				continue;
			}
			if (!first) {
				out.add(Span.plain(blank ? "\n\n" : "\n", false, false));
			}
			first = false;
			blank = false;
			Matcher header = HEADER.matcher(line);
			if (header.matches()) {
				inline(header.group(1), true, false, out);
				continue;
			}
			String trimmed = line.stripLeading();
			if (trimmed.startsWith(">")) {
				out.add(Span.plain("│ ", false, false));
				inline(trimmed.substring(1).stripLeading(), false, true, out);
				continue;
			}
			Matcher bullet = BULLET.matcher(line);
			if (bullet.find()) {
				line = bullet.group(1) + "• " + line.substring(bullet.end());
			}
			inline(line, false, false, out);
		}
		return out;
	}

	private static void inline(String text, boolean bold, boolean italic, List<Span> out) {
		Matcher m = INLINE.matcher(text);
		int last = 0;
		while (m.find()) {
			if (m.start() > last) {
				out.add(Span.plain(text.substring(last, m.start()), bold, italic));
			}
			if (m.group(1) != null) {
				out.add(new Span(m.group(1), bold, italic, true, null, null));
			} else if (m.group(2) != null) {
				out.add(new Span(m.group(2), bold, italic, false, null, m.group(2)));
			} else if (m.group(3) != null) {
				out.add(new Span(m.group(3), bold, italic, false, m.group(4), null));
			} else if (m.group(5) != null) {
				inline(m.group(5), true, italic, out);
			} else {
				inline(m.group(6), bold, true, out);
			}
			last = m.end();
		}
		if (last < text.length()) {
			out.add(Span.plain(text.substring(last), bold, italic));
		}
	}
}
