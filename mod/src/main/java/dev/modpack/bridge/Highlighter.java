package dev.modpack.bridge;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.FloatTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.NbtUtils;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;

/**
 * Временная подсветка блоков (сундуков): светящаяся block_display-копия блока с контуром сквозь стены.
 * Дисплей-сущности ванильные (1.19.4+), клиенту моды не нужны. Сущности помечены тегом и удаляются
 * по таймеру, а если сервер остановился раньше — при следующей загрузке.
 */
public final class Highlighter {
	public static final String TAG = "modpack_bridge_highlight";
	public static final int MAX_BLOCKS = 16;
	private static final int DURATION_TICKS = 30 * 20;
	private static final int GOLD = 0xFFAA00;

	private record Active(Entity entity, long expiresAt) {
	}

	private static final List<Active> ACTIVE = new ArrayList<>();
	private static long tick;

	private Highlighter() {
	}

	public static void register() {
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			tick++;
			for (Iterator<Active> it = ACTIVE.iterator(); it.hasNext(); ) {
				Active active = it.next();
				if (active.expiresAt() <= tick || active.entity().isRemoved()) {
					active.entity().discard();
					it.remove();
				}
			}
		});
		// Остатки после остановки сервера (сущности сохранились вместе с чанком) — убираем при загрузке.
		ServerEntityEvents.ENTITY_LOAD.register((entity, level) -> {
			if (entity.getTags().contains(TAG) && ACTIVE.stream().noneMatch(a -> a.entity() == entity)) {
				entity.discard();
			}
		});
	}

	/** Подсветить блоки на 30 секунд. Возвращает, сколько подсвечено. Серверный поток. */
	public static int highlight(ServerLevel level, List<BlockPos> positions) {
		int count = 0;
		for (BlockPos pos : positions.subList(0, Math.min(positions.size(), MAX_BLOCKS))) {
			if (!level.isLoaded(pos) || level.getBlockState(pos).isAir()) {
				continue;
			}
			Entity display = EntityType.BLOCK_DISPLAY.create(level);
			if (display == null) {
				continue;
			}
			CompoundTag tag = new CompoundTag();
			display.saveWithoutId(tag);
			tag.put("block_state", NbtUtils.writeBlockState(level.getBlockState(pos)));
			tag.putBoolean("Glowing", true);
			tag.putInt("glow_color_override", GOLD);
			// Чуть больше самого блока, чтобы не мерцать с ним в одной плоскости.
			CompoundTag transformation = new CompoundTag();
			transformation.put("left_rotation", floats(0, 0, 0, 1));
			transformation.put("right_rotation", floats(0, 0, 0, 1));
			transformation.put("translation", floats(-0.01f, -0.01f, -0.01f));
			transformation.put("scale", floats(1.02f, 1.02f, 1.02f));
			tag.put("transformation", transformation);
			display.load(tag);
			display.setPos(pos.getX(), pos.getY(), pos.getZ());
			display.addTag(TAG);
			// В список — до добавления в мир: ENTITY_LOAD срабатывает сразу и иначе принял бы её за остаток.
			Active active = new Active(display, tick + DURATION_TICKS);
			ACTIVE.add(active);
			if (level.addFreshEntity(display)) {
				count++;
			} else {
				ACTIVE.remove(active);
			}
		}
		return count;
	}

	private static ListTag floats(float... values) {
		ListTag list = new ListTag();
		for (float value : values) {
			list.add(FloatTag.valueOf(value));
		}
		return list;
	}
}
