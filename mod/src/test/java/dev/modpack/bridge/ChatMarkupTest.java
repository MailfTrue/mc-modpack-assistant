package dev.modpack.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import dev.modpack.bridge.ChatMarkup.Span;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

class ChatMarkupTest {
	private static String plain(List<Span> spans) {
		return spans.stream().map(Span::text).collect(Collectors.joining());
	}

	@Test
	void inlineStyles() {
		List<Span> spans = ChatMarkup.parse("Нужен **железный** *слиток* и `/tp`");
		assertEquals("Нужен железный слиток и /tp", plain(spans));
		assertTrue(spans.get(1).bold());
		assertTrue(spans.get(3).italic());
		assertTrue(spans.get(5).code());
	}

	@Test
	void itemMarkersAndLinks() {
		List<Span> spans = ChatMarkup.parse("Скрафти [[minecraft:crafting_table]], см. [вики](https://wiki.example.com/a_b)");
		Span item = spans.get(1);
		assertEquals("minecraft:crafting_table", item.itemId());
		Span link = spans.get(3);
		assertEquals("вики", link.text());
		assertEquals("https://wiki.example.com/a_b", link.link());
	}

	@Test
	void tagMarkerUsesTagIdWithoutHash() {
		assertEquals("minecraft:planks", ChatMarkup.parse("[[#minecraft:planks]]").get(0).itemId());
	}

	@Test
	void boldWithItemInside() {
		List<Span> spans = ChatMarkup.parse("**возьми [[minecraft:diamond]]**");
		assertTrue(spans.get(0).bold());
		assertEquals("minecraft:diamond", spans.get(1).itemId());
		assertTrue(spans.get(1).bold());
	}

	@Test
	void blocksAndBlankLines() {
		String text = "## Как начать\n\n\n- первое\n* второе\n---\n> цитата\n```\ncode\n```";
		assertEquals("Как начать\n\n• первое\n• второе\n│ цитата\ncode", plain(ChatMarkup.parse(text)));
	}

	@Test
	void snakeCaseIsNotItalic() {
		List<Span> spans = ChatMarkup.parse("iron_ingot_block and 2*3*4");
		assertEquals(1, spans.size());
	}
}
