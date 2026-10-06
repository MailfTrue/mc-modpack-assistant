package dev.modpack.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import net.fabricmc.fabric.api.transfer.v1.item.ItemStorage;
import net.fabricmc.fabric.api.transfer.v1.item.ItemVariant;
import net.fabricmc.fabric.api.transfer.v1.storage.Storage;
import net.fabricmc.fabric.api.transfer.v1.storage.StorageView;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.locale.Language;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.ChestBlock;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.ChestType;
import net.minecraft.world.level.chunk.LevelChunk;

/**
 * Хранилища рядом с игроком (только чтение): сундуки, бочки, шалкеры, модовые хранилища.
 * Честные ограничения: радиус вокруг игрока, загруженные чанки; не показываем нетронутый лут (LootTable, Lootr)
 * и блоки AE2 (ME-сеть смотрится только через me_storage). Вызывать в серверном потоке.
 */
public final class NearbyContainers {
	public static final int RADIUS = 16;
	private static final int MAX_CONTAINERS = 64;
	/** Моды, чьи блоки отдают содержимое ME-сети целиком (интерфейсы, шины) — их не читаем. */
	private static final Set<String> SKIP_NAMESPACES = Set.of(
			"ae2", "extendedae", "megacells", "appbot", "merequester", "ae2wtlib", "lootr");

	private NearbyContainers() {
	}

	public static JsonObject scan(ServerPlayer player) {
		ServerLevel level = player.serverLevel();
		BlockPos center = player.blockPosition();
		List<Found> found = new ArrayList<>();
		int skippedLoot = 0;
		for (int cx = (center.getX() - RADIUS) >> 4; cx <= (center.getX() + RADIUS) >> 4; cx++) {
			for (int cz = (center.getZ() - RADIUS) >> 4; cz <= (center.getZ() + RADIUS) >> 4; cz++) {
				LevelChunk chunk = level.getChunkSource().getChunkNow(cx, cz);
				if (chunk == null) {
					continue; // не загружен — не трогаем
				}
				for (BlockEntity blockEntity : new ArrayList<>(chunk.getBlockEntities().values())) {
					BlockPos pos = blockEntity.getBlockPos();
					if (Math.abs(pos.getX() - center.getX()) > RADIUS || Math.abs(pos.getY() - center.getY()) > RADIUS
							|| Math.abs(pos.getZ() - center.getZ()) > RADIUS) {
						continue;
					}
					try {
						Found container = read(level, blockEntity);
						if (container == null) {
							continue;
						}
						if (container.unlootedLoot) {
							skippedLoot++;
						} else if (!container.items.isEmpty()) {
							found.add(container);
						}
					} catch (Exception | LinkageError ignored) {
						// модовое хранилище с нестандартным поведением — пропускаем
					}
				}
			}
		}
		found.sort(Comparator.comparingDouble(f -> f.pos.distSqr(center)));
		JsonObject out = new JsonObject();
		out.addProperty("radius", RADIUS);
		out.addProperty("player_pos", center.getX() + " " + center.getY() + " " + center.getZ());
		out.addProperty("skipped_unlooted", skippedLoot);
		JsonArray containers = new JsonArray();
		for (Found f : found.subList(0, Math.min(found.size(), MAX_CONTAINERS))) {
			JsonObject json = new JsonObject();
			json.addProperty("block", f.blockId);
			json.addProperty("name", f.blockName);
			json.addProperty("pos", f.pos.getX() + " " + f.pos.getY() + " " + f.pos.getZ());
			json.addProperty("distance", Math.round(Math.sqrt(f.pos.distSqr(center))));
			JsonArray items = new JsonArray();
			f.items.forEach((id, count) -> {
				JsonObject item = new JsonObject();
				item.addProperty("id", id);
				item.addProperty("count", count);
				items.add(item);
			});
			json.add("items", items);
			containers.add(json);
		}
		out.add("containers", containers);
		out.addProperty("total_found", found.size());
		return out;
	}

	private record Found(BlockPos pos, String blockId, String blockName, Map<String, Long> items, boolean unlootedLoot) {
	}

	private static Found read(ServerLevel level, BlockEntity blockEntity) {
		BlockPos pos = blockEntity.getBlockPos();
		BlockState state = blockEntity.getBlockState();
		String blockId = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
		if (SKIP_NAMESPACES.contains(blockId.substring(0, blockId.indexOf(':')))) {
			return null;
		}
		// Двойной сундук: Fabric отдаёт обе половины целиком через каждую — считаем по одной («левой»).
		if (state.hasProperty(ChestBlock.TYPE) && state.getValue(ChestBlock.TYPE) == ChestType.RIGHT) {
			return null;
		}
		Storage<ItemVariant> storage = ItemStorage.SIDED.find(level, pos, state, blockEntity, null);
		if (storage == null && !(blockEntity instanceof Container)) {
			return null; // не хранилище
		}
		String name = Language.getInstance().getOrDefault(state.getBlock().getDescriptionId(), blockId);
		// Нетронутый лут данжа: чтение сгенерировало бы его (и это спойлер) — только считаем.
		CompoundTag tag = blockEntity.saveWithoutMetadata();
		if (tag.contains("LootTable")) {
			return new Found(pos, blockId, name, Map.of(), true);
		}
		Map<String, Long> items = new LinkedHashMap<>();
		if (storage != null) {
			for (StorageView<ItemVariant> view : storage) {
				if (!view.isResourceBlank() && view.getAmount() > 0) {
					String id = BuiltInRegistries.ITEM.getKey(view.getResource().getItem()).toString();
					items.merge(id, view.getAmount(), Long::sum);
				}
			}
		} else {
			Container container = (Container) blockEntity;
			for (int slot = 0; slot < container.getContainerSize(); slot++) {
				ItemStack stack = container.getItem(slot);
				if (!stack.isEmpty()) {
					items.merge(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), (long) stack.getCount(), Long::sum);
				}
			}
		}
		return new Found(pos, blockId, name, items, false);
	}
}
