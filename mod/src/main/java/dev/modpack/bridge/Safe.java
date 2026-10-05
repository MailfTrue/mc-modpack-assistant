package dev.modpack.bridge;

import net.minecraft.locale.Language;
import net.minecraft.world.item.Item;

/**
 * Обращения к предметам других модов. Код модов может падать на сервере даже с Error
 * (например, NoClassDefFoundError на клиентских классах в getName) — такое не должно ронять сервер.
 */
public final class Safe {
	private Safe() {
	}

	/** Ключ перевода предмета без вызова getName/getHoverName мода. */
	public static String translationKey(Item item) {
		try {
			return item.getDescriptionId();
		} catch (Exception | LinkageError e) {
			return "";
		}
	}

	/** Английское название по языковому файлу сервера (без кода предмета). */
	public static String name(Item item, String fallback) {
		String key = translationKey(item);
		if (key.isEmpty()) {
			return fallback;
		}
		return Language.getInstance().getOrDefault(key, fallback);
	}
}
