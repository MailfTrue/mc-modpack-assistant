package dev.modpack.bridge;

import com.google.gson.JsonObject;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.locale.Language;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;

/** /ai в игре: вопрос с контекстом игрока → brain → ответ всем в чат. Всё, кроме сети, — в серверном потоке. */
public final class GameAi {
	private static final int MAX_QUESTION = 500;
	private static final int MAX_NBT = 400;

	private final BridgeClient client;
	private MinecraftServer server;
	/** id вопроса → UUID игрока (null — консоль). Только серверный поток. */
	private final Map<String, UUID> pending = new HashMap<>();

	public GameAi(BridgeClient client) {
		this.client = client;
	}

	public void setServer(MinecraftServer server) {
		this.server = server;
	}

	public void register(CommandDispatcher<CommandSourceStack> dispatcher) {
		dispatcher.register(Commands.literal("ai")
				.then(Commands.argument("question", StringArgumentType.greedyString()).executes(this::ask)));
	}

	private int ask(CommandContext<CommandSourceStack> ctx) {
		CommandSourceStack source = ctx.getSource();
		ServerPlayer player = source.getPlayer();
		String question = StringArgumentType.getString(ctx, "question").strip();
		if (question.length() > MAX_QUESTION) {
			question = question.substring(0, MAX_QUESTION);
		}
		if (!client.isConnected()) {
			source.sendFailure(GameText.aiNotice("ИИ сейчас недоступен (brain не подключён)."));
			return 0;
		}
		UUID uuid = player != null ? player.getUUID() : null;
		if (pending.containsValue(uuid)) {
			source.sendFailure(GameText.aiNotice("Подожди, я ещё думаю над прошлым вопросом."));
			return 0;
		}
		String name = player != null ? player.getGameProfile().getName() : "Console";
		String id = UUID.randomUUID().toString();
		pending.put(id, uuid);

		JsonObject json = new JsonObject();
		json.addProperty("type", "ai_question");
		json.addProperty("id", id);
		json.addProperty("player", name);
		if (uuid != null) {
			json.addProperty("uuid", uuid.toString());
			try {
				json.add("context", context(player));
			} catch (Exception | LinkageError e) {
				// контекст — бонус; вопрос уйдёт и без него
			}
		}
		json.addProperty("question", question);
		client.send(json);

		source.getServer().getPlayerList().broadcastSystemMessage(GameText.question(name, question), false);
		return 1;
	}

	/** Ответ от brain (вызывается в серверном потоке). */
	public void onAnswer(JsonObject message) {
		String id = message.has("id") ? message.get("id").getAsString() : "";
		if (pending.remove(id) == null && !id.isEmpty()) {
			return; // устаревший ответ (например, после переподключения)
		}
		String text = message.has("text") ? message.get("text").getAsString() : "";
		server.getPlayerList().broadcastSystemMessage(GameText.answer(text), false);
	}

	/** Соединение с brain пропало — ответов на висящие вопросы не будет (серверный поток). */
	public void onConnectionLost() {
		if (pending.isEmpty() || server == null) {
			return;
		}
		pending.clear();
		server.getPlayerList().broadcastSystemMessage(GameText.aiNotice("Связь с ИИ пропала, спроси ещё раз чуть позже."), false);
	}

	private static JsonObject context(ServerPlayer player) {
		JsonObject ctx = new JsonObject();
		ctx.addProperty("dimension", player.level().dimension().location().toString());
		BlockPos pos = player.blockPosition();
		ctx.addProperty("position", pos.getX() + " " + pos.getY() + " " + pos.getZ());
		player.level().getBiome(pos).unwrapKey().ifPresent(key -> ctx.addProperty("biome", key.location().toString()));
		addItem(ctx, "main_hand", player.getMainHandItem());
		addItem(ctx, "off_hand", player.getOffhandItem());
		HitResult hit = player.pick(6.0, 0.0f, false);
		if (hit.getType() == HitResult.Type.BLOCK && hit instanceof BlockHitResult blockHit) {
			BlockState state = player.level().getBlockState(blockHit.getBlockPos());
			JsonObject block = new JsonObject();
			block.addProperty("id", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
			block.addProperty("name", Language.getInstance().getOrDefault(state.getBlock().getDescriptionId()));
			ctx.add("looking_at_block", block);
		}
		ctx.addProperty("health", Math.round(player.getHealth()) + "/" + Math.round(player.getMaxHealth()));
		ctx.addProperty("xp_level", player.experienceLevel);
		return ctx;
	}

	private static void addItem(JsonObject ctx, String key, ItemStack stack) {
		if (stack.isEmpty()) {
			return;
		}
		JsonObject item = new JsonObject();
		String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
		item.addProperty("id", id);
		// Своё имя (с наковальни) getHoverName берёт из NBT, не вызывая код предмета; иначе — по языковому файлу.
		item.addProperty("name", stack.hasCustomHoverName() ? stack.getHoverName().getString() : Safe.name(stack.getItem(), id));
		item.addProperty("count", stack.getCount());
		if (stack.getTag() != null) {
			String nbt = stack.getTag().toString();
			item.addProperty("nbt", nbt.length() > MAX_NBT ? nbt.substring(0, MAX_NBT) + "…" : nbt);
		}
		ctx.add(key, item);
	}
}
