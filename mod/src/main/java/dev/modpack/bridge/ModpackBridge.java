package dev.modpack.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.net.URI;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import net.fabricmc.api.DedicatedServerModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.advancements.DisplayInfo;
import net.minecraft.core.BlockPos;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Серверный мост: события сервера → brain (→ Telegram), сообщения и ответы ИИ из brain → игровой чат.
 * Клиентам ставить не нужно.
 */
public final class ModpackBridge implements DedicatedServerModInitializer {
	public static final String MOD_ID = "modpack_bridge";
	private static final Logger LOG = LoggerFactory.getLogger(MOD_ID);

	private static BridgeClient client;
	private static BridgeConfig config;
	private static BrainProcess brain;
	private static GameAi gameAi;
	private static volatile MinecraftServer server;

	@Override
	public void onInitializeServer() {
		Path path = FabricLoader.getInstance().getConfigDir().resolve("modpack-bridge.json");
		try {
			config = BridgeConfig.loadOrCreate(path);
		} catch (Exception e) {
			LOG.error("bridge disabled: cannot read {}: {}", path, e.getMessage());
			return;
		}
		String version = FabricLoader.getInstance().getModContainer(MOD_ID)
				.map(c -> c.getMetadata().getVersion().getFriendlyString()).orElse("?");
		// Папка сервера = родитель config/.
		brain = BrainProcess.fromConfig(config.brain, FabricLoader.getInstance().getConfigDir().getParent());
		if (brain != null) {
			brain.start();
		}
		client = new BridgeClient(URI.create(config.url), config.token, version, new Inbound());
		gameAi = new GameAi(client);
		client.start(brain != null ? Duration.ofSeconds(3) : Duration.ZERO);
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> gameAi.register(dispatcher));
		registerEvents();
		Highlighter.register();
		LOG.info("Modpack Bridge {} started, brain: {}", version, config.url);
	}

	private static void registerEvents() {
		BridgeConfig.Events events = config.events;

		ServerLifecycleEvents.SERVER_STARTING.register(s -> {
			server = s;
			gameAi.setServer(s);
		});
		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			if (events.server) {
				client.send(event("server_started"));
			}
			exportData(server);
		});
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> {
			if (success) {
				exportData(server);
			}
		});
		ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
			if (events.server) {
				client.send(event("server_stopping"));
			}
		});
		ServerLifecycleEvents.SERVER_STOPPED.register(server -> {
			client.shutdown(Duration.ofSeconds(3));
			if (brain != null) {
				brain.stop();
			}
		});

		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
			if (events.joinLeave) {
				client.send(playerEvent("join", handler.getPlayer()));
			}
		});
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> {
			if (events.joinLeave) {
				client.send(playerEvent("leave", handler.getPlayer()));
			}
		});

		ServerLivingEntityEvents.AFTER_DEATH.register((entity, source) -> {
			if (events.death && entity instanceof ServerPlayer player) {
				JsonObject json = playerEvent("death", player);
				json.addProperty("message", source.getLocalizedDeathMessage(player).getString());
				client.send(json);
			}
		});

		ServerMessageEvents.CHAT_MESSAGE.register((message, sender, params) -> {
			if (events.chat) {
				JsonObject json = playerEvent("chat", sender);
				json.addProperty("message", message.decoratedContent().getString());
				client.send(json);
			}
		});
	}

	/** Выгрузка предметов и рецептов для ИИ в <сервер>/modpack-bridge/export (см. DataExport). */
	private static void exportData(MinecraftServer s) {
		if (!config.export) {
			return;
		}
		Path dir = FabricLoader.getInstance().getGameDir().resolve("modpack-bridge").resolve("export");
		try {
			DataExport.run(s, dir, () -> {
				JsonObject json = new JsonObject();
				json.addProperty("type", "data_exported");
				json.addProperty("dir", dir.toAbsolutePath().toString());
				client.send(json);
			});
		} catch (Exception | LinkageError e) {
			// Выгрузка — вспомогательная функция: никогда не роняем из-за неё сервер.
			LOG.error("data export failed", e);
		}
	}

	/** Вызывается из миксина, когда игрок впервые получил достижение. */
	public static void onAdvancement(ServerPlayer player, DisplayInfo display) {
		if (client == null || !config.events.advancement) {
			return;
		}
		JsonObject json = playerEvent("advancement", player);
		json.addProperty("title", display.getTitle().getString());
		json.addProperty("description", display.getDescription().getString());
		json.addProperty("frame", display.getFrame().getName());
		client.send(json);
	}

	/** Сообщения от brain. Приходят в сетевом потоке — вся работа переносится в серверный. */
	private static final class Inbound implements BridgeClient.Handler {
		@Override
		public void onMessage(JsonObject message) {
			MinecraftServer s = server;
			if (s == null) {
				return;
			}
			s.execute(() -> handle(s, message));
		}

		@Override
		public void onConnectionLost() {
			MinecraftServer s = server;
			if (s != null) {
				s.execute(gameAi::onConnectionLost);
			}
		}

		private void handle(MinecraftServer s, JsonObject message) {
			String type = message.has("type") ? message.get("type").getAsString() : "";
			switch (type) {
				case "chat" -> {
					String from = message.has("from") ? message.get("from").getAsString() : "?";
					String text = message.has("text") ? message.get("text").getAsString() : "";
					if (!text.isBlank()) {
						s.getPlayerList().broadcastSystemMessage(GameText.telegram(from, text), false);
					}
				}
				case "ai_answer" -> gameAi.onAnswer(message);
				case "request" -> client.send(response(s, message));
				default -> LOG.debug("unknown message from brain: {}", type);
			}
		}

		private ServerPlayer findPlayer(MinecraftServer s, JsonObject request) {
			String name = request.has("player") ? request.get("player").getAsString() : "";
			return s.getPlayerList().getPlayers().stream()
					.filter(p -> p.getGameProfile().getName().equalsIgnoreCase(name))
					.findFirst().orElse(null);
		}

		private JsonObject response(MinecraftServer s, JsonObject request) {
			JsonObject response = new JsonObject();
			response.addProperty("type", "response");
			response.add("id", request.get("id"));
			String method = request.has("method") ? request.get("method").getAsString() : "";
			if (method.equals("online")) {
				JsonArray players = new JsonArray();
				s.getPlayerList().getPlayers().forEach(p -> players.add(p.getGameProfile().getName()));
				JsonObject result = new JsonObject();
				result.add("players", players);
				result.addProperty("max", s.getPlayerList().getMaxPlayers());
				response.add("result", result);
			} else if (method.equals("highlight")) {
				ServerPlayer player = findPlayer(s, request);
				if (player == null) {
					response.addProperty("error", "игрок не в сети");
				} else {
					List<BlockPos> positions = new ArrayList<>();
					if (request.has("positions")) {
						for (var element : request.getAsJsonArray("positions")) {
							String[] xyz = element.getAsString().split(" ");
							positions.add(new BlockPos(
									Integer.parseInt(xyz[0]), Integer.parseInt(xyz[1]), Integer.parseInt(xyz[2])));
						}
					}
					JsonObject result = new JsonObject();
					result.addProperty("highlighted", Highlighter.highlight(player.serverLevel(), positions));
					result.addProperty("seconds", 30);
					response.add("result", result);
				}
			} else if (method.equals("nearby_containers")) {
				ServerPlayer player = findPlayer(s, request);
				if (player == null) {
					response.addProperty("error", "игрок не в сети");
				} else {
					try {
						response.add("result", NearbyContainers.scan(player));
					} catch (Exception | LinkageError e) {
						response.addProperty("error", "не удалось осмотреть хранилища: " + e);
					}
				}
			} else if (method.equals("me_storage")) {
				ServerPlayer player = findPlayer(s, request);
				if (!FabricLoader.getInstance().isModLoaded("ae2")) {
					response.addProperty("error", "Applied Energistics 2 не установлен");
				} else if (player == null) {
					response.addProperty("error", "игрок не в сети");
				} else {
					try {
						response.add("result", Ae2Access.storage(player, gameAi.recentMeBlock(player.getUUID())));
					} catch (Exception | LinkageError e) {
						response.addProperty("error", "не удалось прочитать ME-сеть: " + e);
					}
				}
			} else if (method.equals("inventory")) {
				String name = request.has("player") ? request.get("player").getAsString() : "";
				ServerPlayer player = s.getPlayerList().getPlayers().stream()
						.filter(p -> p.getGameProfile().getName().equalsIgnoreCase(name))
						.findFirst().orElse(null);
				if (player == null) {
					response.addProperty("error", "игрок " + name + " не в сети");
				} else {
					try {
						response.add("result", InventoryExport.of(player));
					} catch (Exception | LinkageError e) {
						response.addProperty("error", "не удалось прочитать инвентарь: " + e);
					}
				}
			} else {
				response.addProperty("error", "unknown method: " + method);
			}
			return response;
		}
	}

	private static JsonObject event(String name) {
		JsonObject json = new JsonObject();
		json.addProperty("type", "event");
		json.addProperty("event", name);
		json.addProperty("ts", System.currentTimeMillis());
		return json;
	}

	private static JsonObject playerEvent(String name, ServerPlayer player) {
		JsonObject json = event(name);
		json.addProperty("player", player.getGameProfile().getName());
		json.addProperty("uuid", player.getUUID().toString());
		return json;
	}
}
