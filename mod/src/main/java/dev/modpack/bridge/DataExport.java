package dev.modpack.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.core.NonNullList;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.AbstractCookingRecipe;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.ShapedRecipe;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Выгрузка итоговых данных сервера для ИИ: предметы, теги, рецепты, моды.
 * Берём из реестров работающего сервера, а не из jar-файлов: так учтены датапаки, условия загрузки рецептов,
 * AlmostUnified и прочие изменения во время загрузки. Собираем в серверном потоке, пишем на диск — в фоне.
 */
public final class DataExport {
	public static final int FORMAT = 1;
	private static final Logger LOG = LoggerFactory.getLogger("modpack_bridge");
	private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().create();

	private DataExport() {
	}

	/** Вызывать в серверном потоке. Возвращает поток записи (уже запущен). */
	public static Thread run(MinecraftServer server, Path dir, Runnable onDone) {
		long started = System.currentTimeMillis();
		JsonObject items = items();
		JsonObject tags = tags();
		JsonArray recipes = new JsonArray();
		int failed = 0;
		for (Recipe<?> recipe : server.getRecipeManager().getRecipes()) {
			try {
				recipes.add(recipe(server, recipe));
			} catch (Exception | LinkageError e) {
				failed++;
			}
		}
		JsonArray mods = mods();
		JsonObject meta = new JsonObject();
		meta.addProperty("format", FORMAT);
		meta.addProperty("exported_at", System.currentTimeMillis());
		meta.addProperty("items", items.size());
		meta.addProperty("recipes", recipes.size());
		meta.addProperty("recipes_failed", failed);
		meta.addProperty("mods", mods.size());
		long collectMs = System.currentTimeMillis() - started;
		int failedCount = failed;

		Thread writer = new Thread(() -> {
			try {
				Files.createDirectories(dir);
				write(dir.resolve("items.json"), items);
				write(dir.resolve("tags.json"), tags);
				write(dir.resolve("recipes.json"), recipes);
				write(dir.resolve("mods.json"), mods);
				// meta — последним: brain по нему понимает, что выгрузка целиком готова.
				write(dir.resolve("meta.json"), meta);
				LOG.info("exported {} items, {} recipes ({} failed), {} mods to {} (collect {} ms)",
						items.size(), recipes.size(), failedCount, mods.size(), dir, collectMs);
				onDone.run();
			} catch (IOException e) {
				LOG.error("data export failed: {}", e.getMessage());
			}
		}, "modpack-bridge-export");
		writer.setDaemon(true);
		writer.start();
		return writer;
	}

	private static JsonObject items() {
		JsonObject out = new JsonObject();
		for (Item item : BuiltInRegistries.ITEM) {
			ResourceLocation id = BuiltInRegistries.ITEM.getKey(item);
			JsonObject json = new JsonObject();
			json.addProperty("key", Safe.translationKey(item));
			json.addProperty("name", Safe.name(item, id.getPath()));
			out.add(id.toString(), json);
		}
		return out;
	}

	private static JsonObject tags() {
		JsonObject out = new JsonObject();
		BuiltInRegistries.ITEM.getTags().forEach(pair -> {
			JsonArray members = new JsonArray();
			pair.getSecond().forEach(holder -> members.add(BuiltInRegistries.ITEM.getKey(holder.value()).toString()));
			if (!members.isEmpty()) {
				out.add(pair.getFirst().location().toString(), members);
			}
		});
		return out;
	}

	private static JsonObject recipe(MinecraftServer server, Recipe<?> recipe) {
		JsonObject json = new JsonObject();
		json.addProperty("id", recipe.getId().toString());
		json.addProperty("type", String.valueOf(BuiltInRegistries.RECIPE_TYPE.getKey(recipe.getType())));
		json.addProperty("serializer", String.valueOf(BuiltInRegistries.RECIPE_SERIALIZER.getKey(recipe.getSerializer())));
		ItemStack result = ItemStack.EMPTY;
		try {
			result = recipe.getResultItem(server.registryAccess());
		} catch (Exception | LinkageError ignored) {
			// у части модовых рецептов результат зависит от входа — оставляем пустым
		}
		if (result != null && !result.isEmpty()) {
			json.addProperty("result", BuiltInRegistries.ITEM.getKey(result.getItem()).toString());
			json.addProperty("count", result.getCount());
		}
		NonNullList<Ingredient> ingredients;
		try {
			ingredients = recipe.getIngredients();
		} catch (Exception | LinkageError e) {
			ingredients = NonNullList.create();
		}
		JsonArray inputs = new JsonArray();
		for (Ingredient ingredient : ingredients) {
			inputs.add(ingredient(ingredient));
		}
		json.add("ingredients", inputs);
		if (recipe instanceof ShapedRecipe shaped) {
			json.addProperty("width", shaped.getWidth());
			json.addProperty("height", shaped.getHeight());
		}
		if (recipe instanceof AbstractCookingRecipe cooking) {
			json.addProperty("time", cooking.getCookingTime());
			json.addProperty("xp", cooking.getExperience());
		}
		return json;
	}

	/** {"tag": "c:ingots/iron"} или {"items": [...]}; пустой ингредиент (дырка в сетке) — null. */
	private static JsonElement ingredient(Ingredient ingredient) {
		if (ingredient.isEmpty()) {
			return JsonNull.INSTANCE;
		}
		try {
			JsonElement json = ingredient.toJson();
			if (json.isJsonObject() && json.getAsJsonObject().has("tag")) {
				JsonObject out = new JsonObject();
				out.add("tag", json.getAsJsonObject().get("tag"));
				return out;
			}
		} catch (Exception | LinkageError ignored) {
			// нестандартный ингредиент — ниже развернём в список предметов
		}
		JsonArray items = new JsonArray();
		ItemStack[] stacks;
		try {
			stacks = ingredient.getItems();
		} catch (Exception | LinkageError e) {
			stacks = new ItemStack[0];
		}
		for (ItemStack stack : stacks) {
			String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
			if (!items.contains(new JsonPrimitive(id))) {
				items.add(id);
			}
		}
		JsonObject out = new JsonObject();
		out.add("items", items);
		return out;
	}

	private static JsonArray mods() {
		JsonArray out = new JsonArray();
		FabricLoader.getInstance().getAllMods().forEach(mod -> {
			JsonObject json = new JsonObject();
			json.addProperty("id", mod.getMetadata().getId());
			json.addProperty("name", mod.getMetadata().getName());
			json.addProperty("version", mod.getMetadata().getVersion().getFriendlyString());
			if (mod.getContainingMod().isEmpty()) {
				out.add(json); // вложенные библиотеки (jar-in-jar) не нужны
			}
		});
		return out;
	}

	private static void write(Path path, JsonElement json) throws IOException {
		Path tmp = path.resolveSibling(path.getFileName() + ".tmp");
		try (Writer writer = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
			GSON.toJson(json, writer);
		}
		Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
	}
}
