package dev.modpack.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Map;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.Tag;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
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
		try {
			JsonArray accessories = accessories(player);
			if (accessories != null) {
				out.add("accessories", accessories);
			}
		} catch (Exception | LinkageError e) {
			out.addProperty("accessories_error", e.toString());
		}
		try {
			ItemStack backpack = wornBackpack(player);
			if (backpack != null && !backpack.isEmpty()) {
				out.add("worn_backpack", item(backpack, true));
			}
		} catch (Exception | LinkageError e) {
			out.addProperty("worn_backpack_error", e.toString());
		}
		return out;
	}

	/** Рюкзак Traveler's Backpack, надетый на спину (хранится в компоненте игрока, а не в слоте). */
	private static ItemStack wornBackpack(ServerPlayer player) throws ReflectiveOperationException {
		if (!FabricLoader.getInstance().isModLoaded("travelersbackpack")) {
			return null;
		}
		Class<?> utils = Class.forName("com.tiviacz.travelersbackpack.component.ComponentUtils");
		Object component = utils.getMethod("getComponent", Player.class).invoke(null, player);
		if (component == null) {
			return null;
		}
		return (ItemStack) component.getClass().getMethod("getWearable").invoke(component);
	}

	/**
	 * Доп. слоты мода Accessories (кольца, амулеты, пояса, спина…). Через рефлексию, без зависимости при сборке:
	 * если мода нет или его API поменялся, просто ничего не добавляем. null — мода нет.
	 */
	private static JsonArray accessories(ServerPlayer player) throws ReflectiveOperationException {
		if (!FabricLoader.getInstance().isModLoaded("accessories")) {
			return null;
		}
		Class<?> capabilityClass = Class.forName("io.wispforest.accessories.api.AccessoriesCapability");
		Object capability = capabilityClass.getMethod("get", LivingEntity.class).invoke(null, player);
		JsonArray out = new JsonArray();
		if (capability == null) {
			return out;
		}
		Map<?, ?> containers = (Map<?, ?>) capabilityClass.getMethod("getContainers").invoke(capability);
		for (Map.Entry<?, ?> entry : containers.entrySet()) {
			Object container = entry.getValue();
			Class<?> containerClass = container.getClass();
			JsonArray equipped = stacks((Container) containerClass.getMethod("getAccessories").invoke(container));
			JsonArray cosmetic = stacks((Container) containerClass.getMethod("getCosmeticAccessories").invoke(container));
			if (equipped.isEmpty() && cosmetic.isEmpty()) {
				continue;
			}
			JsonObject slot = new JsonObject();
			slot.addProperty("slot", String.valueOf(entry.getKey()));
			slot.add("items", equipped);
			if (!cosmetic.isEmpty()) {
				slot.add("cosmetic", cosmetic);
			}
			out.add(slot);
		}
		return out;
	}

	private static JsonArray stacks(Container container) {
		JsonArray out = new JsonArray();
		for (int i = 0; i < container.getContainerSize(); i++) {
			ItemStack stack = container.getItem(i);
			if (!stack.isEmpty()) {
				out.add(item(stack, true));
			}
		}
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
			JsonObject contents = new JsonObject();
			try {
				collectContents(tag, "items", 0, contents);
			} catch (Exception | LinkageError ignored) {
				// нестандартный формат хранения — без содержимого
			}
			if (contents.size() > 0) {
				json.add("contents", contents);
				for (String tank : new String[] {"LeftTank", "RightTank"}) {
					if (tag.contains(tank)) {
						json.addProperty(tank, clip(tag.get(tank).toString(), 150));
					}
				}
			} else if (detailed) {
				// У контейнеров NBT огромный и уже разобран в contents — сырой показываем только у прочих.
				json.addProperty("nbt", clip(tag.toString(), 300));
			}
		}
		return json;
	}

	/**
	 * Содержимое предметов-контейнеров: любой список "Items" внутри NBT (рюкзаки Traveler's Backpack —
	 * Inventory/ToolsInventory/CraftingInventory, шалкеры — BlockEntityTag, мешочки — Items).
	 * Метка — имя родительского ключа. Вложенные контейнеры раскрываем на один уровень.
	 */
	private static void collectContents(CompoundTag tag, String label, int depth, JsonObject out) {
		for (String key : tag.getAllKeys()) {
			Tag value = tag.get(key);
			if (key.equals("Items") && value instanceof ListTag list && list.getElementType() == Tag.TAG_COMPOUND) {
				JsonArray items = listItems(list, depth);
				if (!items.isEmpty()) {
					out.add(label, items);
				}
			} else if (value instanceof CompoundTag child && depth < 3) {
				collectContents(child, key.equals("BlockEntityTag") ? label : key, depth + 1, out);
			}
		}
	}

	private static JsonArray listItems(ListTag list, int depth) {
		Map<String, JsonObject> grouped = new LinkedHashMap<>();
		JsonArray containers = new JsonArray();
		for (int i = 0; i < list.size(); i++) {
			CompoundTag entry = list.getCompound(i);
			String id = entry.getString("id");
			int count = entry.contains("Count") ? entry.getInt("Count") : entry.getInt("count");
			if (id.isEmpty() || count <= 0) {
				continue;
			}
			JsonObject json = new JsonObject();
			json.addProperty("id", id);
			json.addProperty("count", count);
			ResourceLocation location = ResourceLocation.tryParse(id);
			json.addProperty("name", location == null
					? id
					: BuiltInRegistries.ITEM.getOptional(location).map(item -> Safe.name(item, id)).orElse(id));
			if (depth < 2 && entry.contains("tag", Tag.TAG_COMPOUND)) {
				JsonObject nested = new JsonObject();
				collectContents(entry.getCompound("tag"), "items", depth + 1, nested);
				if (nested.size() > 0) {
					json.add("contents", nested);
					containers.add(json); // контейнеры с содержимым не склеиваем
					continue;
				}
			}
			JsonObject existing = grouped.get(id);
			if (existing != null) {
				existing.addProperty("count", existing.get("count").getAsInt() + count);
			} else {
				grouped.put(id, json);
			}
		}
		JsonArray out = new JsonArray();
		grouped.values().forEach(out::add);
		containers.forEach(out::add);
		return out;
	}

	private static String clip(String text, int max) {
		return text.length() > max ? text.substring(0, max) + "…" : text;
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
