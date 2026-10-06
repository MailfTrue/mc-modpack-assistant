package dev.modpack.bridge;

import appeng.api.networking.IGrid;
import appeng.api.networking.IGridNode;
import appeng.api.networking.IInWorldGridNodeHost;
import appeng.api.stacks.AEItemKey;
import appeng.api.stacks.AEKey;
import appeng.api.stacks.KeyCounter;
import appeng.items.tools.powered.WirelessTerminalItem;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import it.unimi.dsi.fastutil.objects.Object2LongMap;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.GlobalPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.entity.BlockEntity;

/**
 * Доступ к ME-сети Applied Energistics 2 (только чтение). Класс трогает API AE2 напрямую, поэтому
 * загружается только если AE2 установлен — вызывать через {@link #storage} после проверки isModLoaded("ae2").
 */
final class Ae2Access {
	static final int MAX_ENTRIES = 5000;

	private Ae2Access() {
	}

	/** Это блок ME-сети (кабель, терминал, привод…)? */
	static boolean isGridBlock(ServerLevel level, BlockPos pos) {
		return gridAt(level, pos) != null;
	}

	/**
	 * Содержимое сети игрока. Сеть ищем: сначала по ME-блоку, на который игрок недавно смотрел (/ai),
	 * затем по привязанному беспроводному терминалу в инвентаре.
	 */
	static JsonObject storage(ServerPlayer player, GlobalPos lookedAt) {
		JsonObject out = new JsonObject();
		IGrid grid = null;
		String source = null;
		if (lookedAt != null && lookedAt.dimension() == player.level().dimension()) {
			grid = gridAt(player.serverLevel(), lookedAt.pos());
			if (grid != null) {
				BlockPos pos = lookedAt.pos();
				source = "ME-блок на " + pos.getX() + " " + pos.getY() + " " + pos.getZ();
			}
		}
		if (grid == null) {
			Inventory inv = player.getInventory();
			List<ItemStack> stacks = new ArrayList<>(inv.items);
			stacks.addAll(inv.offhand);
			for (ItemStack stack : stacks) {
				if (stack.getItem() instanceof WirelessTerminalItem terminal) {
					grid = terminal.getLinkedGrid(stack, player.level(), null);
					if (grid != null) {
						source = "беспроводной терминал (" + Safe.name(stack.getItem(), "terminal") + ")";
						break;
					}
				}
			}
		}
		if (grid == null) {
			out.addProperty("error", "ME-сеть не найдена: в инвентаре нет привязанного беспроводного терминала "
					+ "(или его точка доступа в незагруженном чанке), и игрок не смотрел на ME-блок при вопросе /ai.");
			return out;
		}
		out.addProperty("source", source);
		out.addProperty("powered", grid.getEnergyService().isNetworkPowered());

		KeyCounter inventory = grid.getStorageService().getCachedInventory();
		List<Object2LongMap.Entry<AEKey>> entries = new ArrayList<>();
		for (Object2LongMap.Entry<AEKey> entry : inventory) {
			if (entry.getLongValue() > 0) {
				entries.add(entry);
			}
		}
		entries.sort(Comparator.comparingLong((Object2LongMap.Entry<AEKey> e) -> e.getLongValue()).reversed());
		out.addProperty("total_types", entries.size());
		JsonArray items = new JsonArray();
		for (Object2LongMap.Entry<AEKey> entry : entries.subList(0, Math.min(entries.size(), MAX_ENTRIES))) {
			items.add(key(entry.getKey(), entry.getLongValue()));
		}
		out.add("items", items);

		Set<AEKey> craftables = grid.getCraftingService().getCraftables(key -> true);
		JsonArray craftable = new JsonArray();
		craftables.stream().limit(MAX_ENTRIES).forEach(key -> craftable.add(key.getId().toString()));
		out.add("craftable", craftable);
		return out;
	}

	private static JsonObject key(AEKey key, long amount) {
		JsonObject json = new JsonObject();
		String id = key.getId().toString();
		json.addProperty("id", id);
		json.addProperty("amount", amount);
		if (key instanceof AEItemKey item) {
			json.addProperty("name", Safe.name(item.getItem(), id));
		} else {
			json.addProperty("type", key.getType().getId().toString());
		}
		return json;
	}

	private static IGrid gridAt(ServerLevel level, BlockPos pos) {
		if (!level.isLoaded(pos)) {
			return null;
		}
		BlockEntity blockEntity = level.getBlockEntity(pos);
		if (!(blockEntity instanceof IInWorldGridNodeHost host)) {
			return null;
		}
		// У кабеля узлы по сторонам и в центре (null) — берём первый, у которого есть сеть.
		List<Direction> sides = new ArrayList<>();
		sides.add(null);
		sides.addAll(List.of(Direction.values()));
		for (Direction side : sides) {
			IGridNode node = host.getGridNode(side);
			if (node != null && node.getGrid() != null) {
				return node.getGrid();
			}
		}
		return null;
	}
}
