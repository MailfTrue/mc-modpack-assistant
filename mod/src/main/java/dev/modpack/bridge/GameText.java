package dev.modpack.bridge;

import dev.modpack.bridge.ChatMarkup.Span;
import java.util.Optional;
import net.minecraft.ChatFormatting;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.HoverEvent;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.chat.Style;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

/** Сообщения мода в игровом чате. */
public final class GameText {
	private static final int MAX_TG_TEXT = 256;

	private GameText() {
	}

	public static MutableComponent aiPrefix() {
		return Component.literal("[ИИ] ").withStyle(ChatFormatting.GOLD);
	}

	public static Component question(String player, String question) {
		return aiPrefix()
				.append(Component.literal(player + " спрашивает: ").withStyle(ChatFormatting.GRAY))
				.append(Component.literal(question).withStyle(ChatFormatting.GRAY, ChatFormatting.ITALIC));
	}

	public static Component aiNotice(String text) {
		return aiPrefix().append(Component.literal(text).withStyle(ChatFormatting.GRAY));
	}

	public static Component answer(String markdown) {
		MutableComponent out = aiPrefix();
		for (Span span : ChatMarkup.parse(markdown)) {
			out.append(span(span));
		}
		return out;
	}

	public static Component telegram(String from, String text) {
		String clipped = text.length() > MAX_TG_TEXT ? text.substring(0, MAX_TG_TEXT) + "…" : text;
		return Component.literal("[TG] ").withStyle(ChatFormatting.AQUA)
				.append(Component.literal(from).withStyle(ChatFormatting.YELLOW))
				.append(Component.literal(": " + clipped).withStyle(ChatFormatting.WHITE));
	}

	private static MutableComponent span(Span span) {
		MutableComponent part;
		if (span.itemId() != null) {
			part = item(span.itemId());
		} else if (span.link() != null) {
			part = Component.literal(span.text()).withStyle(Style.EMPTY
					.withColor(ChatFormatting.BLUE)
					.withUnderlined(true)
					.withClickEvent(new ClickEvent(ClickEvent.Action.OPEN_URL, span.link()))
					.withHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_TEXT, Component.literal(span.link()))));
		} else if (span.code()) {
			part = Component.literal(span.text()).withStyle(Style.EMPTY
					.withColor(ChatFormatting.GRAY)
					.withClickEvent(new ClickEvent(ClickEvent.Action.COPY_TO_CLIPBOARD, span.text()))
					.withHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_TEXT, Component.literal("Скопировать"))));
		} else {
			part = Component.literal(span.text());
		}
		if (span.bold()) {
			part.withStyle(ChatFormatting.BOLD);
		}
		if (span.italic()) {
			part.withStyle(ChatFormatting.ITALIC);
		}
		return part;
	}

	/** Название предмета (переводится на клиенте) с его тултипом при наведении; неизвестный id — серым текстом. */
	private static MutableComponent item(String id) {
		Optional<Item> item = Optional.ofNullable(ResourceLocation.tryParse(id)).flatMap(BuiltInRegistries.ITEM::getOptional);
		if (item.isEmpty() || item.get() == Items.AIR) {
			return Component.literal(id).withStyle(ChatFormatting.GRAY);
		}
		ItemStack stack = new ItemStack(item.get());
		// Ключ перевода, а не getHoverName(): название подставит клиент на своём языке, а код мода не вызывается.
		Component name = Component.translatable(Safe.translationKey(item.get()));
		return Component.literal("[").append(name).append("]").withStyle(Style.EMPTY
				.withColor(ChatFormatting.AQUA)
				.withHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_ITEM, new HoverEvent.ItemStackInfo(stack))));
	}
}
