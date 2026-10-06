package dev.modpack.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class BookViewTest {
	@Test
	void questionOnFirstPageAndPagesFit() {
		String answer = String.join("\n", java.util.Collections.nCopies(40, "Строка ответа про боссов и квесты."));
		List<String> pages = BookView.paginate("Как убить Gauntlet?", answer);
		assertTrue(pages.get(0).startsWith("*Как убить Gauntlet?*"));
		assertTrue(pages.size() > 3);
		for (String page : pages) {
			assertTrue(page.length() <= BookView.PAGE_CHARS + 1, "page too long: " + page.length());
			assertFalse(page.isBlank());
		}
	}

	@Test
	void longLineWrappedByWords() {
		String longLine = "слово ".repeat(200).strip();
		List<String> pages = BookView.paginate(null, longLine);
		assertTrue(pages.size() > 1);
		assertEquals(longLine.replace(" ", ""), String.join("", pages).replace("\n", "").replace(" ", ""));
	}

	@Test
	void previewAndLongDetection() {
		assertFalse(GameText.isLong("коротко"));
		String text = "Первый абзац с сутью.\n\n" + "Детали. ".repeat(100);
		assertTrue(GameText.isLong(text));
		String preview = GameText.preview(text);
		assertTrue(preview.startsWith("Первый абзац с сутью."));
		assertTrue(preview.length() <= GameText.PREVIEW_CHARS + 2);
	}
}
