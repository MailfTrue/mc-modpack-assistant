package dev.modpack.bridge;

import com.google.gson.JsonObject;
import java.net.URI;
import java.nio.file.Path;
import java.time.Duration;
import net.fabricmc.api.DedicatedServerModInitializer;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.advancements.DisplayInfo;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Серверный мост: события сервера → brain (→ Telegram). Клиентам ставить не нужно. */
public final class ModpackBridge implements DedicatedServerModInitializer {
	public static final String MOD_ID = "modpack_bridge";
	private static final Logger LOG = LoggerFactory.getLogger(MOD_ID);

	private static BridgeClient client;
	private static BridgeConfig config;

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
		client = new BridgeClient(URI.create(config.url), config.token, version);
		client.start();
		registerEvents();
		LOG.info("Modpack Bridge {} started, brain: {}", version, config.url);
	}

	private static void registerEvents() {
		BridgeConfig.Events events = config.events;

		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			if (events.server) {
				client.send(event("server_started"));
			}
		});
		ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
			if (events.server) {
				client.send(event("server_stopping"));
			}
		});
		ServerLifecycleEvents.SERVER_STOPPED.register(server -> client.shutdown(Duration.ofSeconds(3)));

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
