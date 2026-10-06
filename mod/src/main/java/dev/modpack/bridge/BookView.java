package dev.modpack.bridge;

import java.util.ArrayList;
import java.util.List;
import net.minecraft.ChatFormatting;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.StringTag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundContainerSetSlotPacket;
import net.minecraft.network.protocol.game.ClientboundOpenBookPacket;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

/**
 * Длинный ответ ИИ в виде книги. Открывается без клиентских модов: клиенту на мгновение показываем
 * книгу в руке (только пакетом — инвентарь на сервере не меняется), открываем экран книги и сразу
 * возвращаем настоящий предмет. Экран книги копирует страницы при открытии, так что подмена незаметна.
 */
public final class BookView {
	/** Примерно столько влезает на страницу книги (14 строк по ~19 символов, с запасом на переносы). */
	static final int PAGE_CHARS = 190;
	static final int PAGE_LINES = 12;
	private static final int MAX_PAGES = 100;

	private BookView() {
	}

	public static void open(ServerPlayer player, String question, String markdown) {
		ItemStack book = new ItemStack(Items.WRITTEN_BOOK);
		CompoundTag tag = book.getOrCreateTag();
		tag.putString("title", "Ответ ИИ");
		tag.putString("author", "ИИ");
		tag.putBoolean("resolved", true);
		ListTag pages = new ListTag();
		for (String page : paginate(question, markdown)) {
			pages.add(StringTag.valueOf(Component.Serializer.toJson(GameText.page(page))));
		}
		tag.put("pages", pages);

		int slot = player.getInventory().selected;
		// containerId -2: прямая запись в слот инвентаря игрока на клиенте.
		player.connection.send(new ClientboundContainerSetSlotPacket(-2, 0, slot, book));
		player.connection.send(new ClientboundOpenBookPacket(InteractionHand.MAIN_HAND));
		player.connection.send(new ClientboundContainerSetSlotPacket(-2, 0, slot, player.getInventory().getItem(slot)));
	}

	/** Markdown → страницы: по строкам, длинные строки — по словам; первая страница начинается с вопроса. */
	static List<String> paginate(String question, String markdown) {
		List<String> lines = new ArrayList<>();
		if (question != null && !question.isBlank()) {
			lines.add("*" + question.strip().replace("*", "") + "*");
			lines.add("");
		}
		for (String line : markdown.strip().replace("\r", "").split("\n")) {
			lines.addAll(wrap(line, PAGE_CHARS));
		}
		List<String> pages = new ArrayList<>();
		StringBuilder page = new StringBuilder();
		int pageLines = 0;
		for (String line : lines) {
			int visualLines = Math.max(1, (line.length() + 18) / 19);
			if (page.length() > 0 && (page.length() + line.length() > PAGE_CHARS || pageLines + visualLines > PAGE_LINES)) {
				pages.add(page.toString().strip());
				page.setLength(0);
				pageLines = 0;
				if (line.isBlank()) {
					continue; // пустая строка в начале страницы не нужна
				}
			}
			page.append(line).append('\n');
			pageLines += visualLines;
		}
		if (!page.toString().isBlank()) {
			pages.add(page.toString().strip());
		}
		if (pages.size() > MAX_PAGES) {
			pages = new ArrayList<>(pages.subList(0, MAX_PAGES));
			pages.set(MAX_PAGES - 1, pages.get(MAX_PAGES - 1) + "\n…");
		}
		return pages;
	}

	private static List<String> wrap(String line, int max) {
		List<String> out = new ArrayList<>();
		String rest = line;
		while (rest.length() > max) {
			int cut = rest.lastIndexOf(' ', max);
			if (cut <= 0) {
				cut = max;
			}
			out.add(rest.substring(0, cut));
			rest = rest.substring(cut).stripLeading();
		}
		out.add(rest);
		return out;
	}

	/** Отметка в чате, если ответа уже нет в памяти. */
	static Component expired() {
		return GameText.aiNotice("Этот ответ уже не сохранён — спроси заново.").copy().withStyle(ChatFormatting.GRAY);
	}
}
