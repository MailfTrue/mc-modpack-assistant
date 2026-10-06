package dev.modpack.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Map;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.Tag;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;

/** Инвентарь игрока для ИИ (по запросу brain). Вызывать в серверном потоке. */
public final class InventoryExport {
	private static final String[] ARMOR = {"feet", "legs", "chest", "head"};

	private InventoryExport() {
	}

	public static JsonObject of(ServerPlayer player) {
		Inventory inv = player.getInventory();
		JsonObject out = new JsonObject();
		out.addProperty("player", player.getGameProfile().getName());
		out.addProperty("selected_hotbar_slot", inv.selected + 1);

		JsonObject armor = new JsonObject();
		for (int i = 0; i < inv.armor.size(); i++) {
			if (!inv.armor.get(i).isEmpty()) {
				armor.add(ARMOR[Math.min(i, ARMOR.length - 1)], item(inv.armor.get(i), true));
			}
		}
		out.add("armor", armor);
		if (!inv.offhand.get(0).isEmpty()) {
			out.add("off_hand", item(inv.offhand.get(0), true));
		}

		JsonArray hotbar = new JsonArray();
		for (int slot = 0; slot < 9; slot++) {
			ItemStack stack = inv.items.get(slot);
			if (!stack.isEmpty()) {
				JsonObject json = item(stack, true);
				json.addProperty("slot", slot + 1);
				hotbar.add(json);
			}
		}
		out.add("hotbar", hotbar);
		out.add("main", grouped(inv, 9, inv.items.size()));
		out.add("ender_chest", grouped(player.getEnderChestInventory(), 0, player.getEnderChestInventory().getContainerSize()));
		return out;
	}

	/** Основной инвентарь и эндер-сундук: одинаковые предметы складываем, чтобы не раздувать ответ. */
	private static JsonArray grouped(Container container, int from, int to) {
		Map<String, JsonObject> byKey = new LinkedHashMap<>();
		for (int slot = from; slot < to; slot++) {
			ItemStack stack = container.getItem(slot);
			if (stack.isEmpty()) {
				continue;
			}
			JsonObject json = item(stack, false);
			// Зачарованные/повреждённые предметы не склеиваем с обычными.
			String key = json.get("id").getAsString() + json.has("enchantments") + json.has("durability");
			JsonObject existing = byKey.get(key);
			if (existing != null) {
				existing.addProperty("count", existing.get("count").getAsInt() + stack.getCount());
			} else {
				byKey.put(key, json);
			}
		}
		JsonArray out = new JsonArray();
		byKey.values().forEach(out::add);
		return out;
	}

	private static JsonObject item(ItemStack stack, boolean detailed) {
		JsonObject json = new JsonObject();
		String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
		json.addProperty("id", id);
		json.addProperty("count", stack.getCount());
		try {
			json.addProperty("name", stack.hasCustomHoverName()
					? stack.getHoverName().getString()
					: Safe.name(stack.getItem(), id));
		} catch (Exception | LinkageError e) {
			json.addProperty("name", id);
		}
		try {
			if (stack.isDamageableItem() && stack.getDamageValue() > 0) {
				json.addProperty("durability", (stack.getMaxDamage() - stack.getDamageValue()) + "/" + stack.getMaxDamage());
			}
		} catch (Exception | LinkageError ignored) {
			// прочность у модовых предметов может считаться нестандартно
		}
		CompoundTag tag = stack.getTag();
		if (tag != null) {
			JsonArray enchants = enchantments(tag);
			if (!enchants.isEmpty()) {
				json.add("enchantments", enchants);
			}
			if (detailed) {
				String nbt = tag.toString();
				json.addProperty("nbt", nbt.length() > 300 ? nbt.substring(0, 300) + "…" : nbt);
			}
		}
		return json;
	}

	private static JsonArray enchantments(CompoundTag tag) {
		JsonArray out = new JsonArray();
		for (String key : new String[] {"Enchantments", "StoredEnchantments"}) {
			ListTag list = tag.getList(key, Tag.TAG_COMPOUND);
			for (int i = 0; i < list.size(); i++) {
				CompoundTag enchant = list.getCompound(i);
				out.add(enchant.getString("id") + " " + enchant.getShort("lvl"));
			}
		}
		return out;
	}
}
