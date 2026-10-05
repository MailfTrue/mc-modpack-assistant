package dev.modpack.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParseException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

/**
 * config/modpack-bridge.json — единый конфиг и мода, и brain (brain читает тот же файл).
 * При первом запуске создаётся с новым случайным токеном моста. Закрыт от чтения ИИ.
 */
public final class BridgeConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().serializeNulls().create();

	public String url = "ws://127.0.0.1:8765";
	public String token = "";
	public Brain brain = new Brain();
	public Telegram telegram = new Telegram();
	public Llm llm = new Llm();
	public Events events = new Events();
	/** Выгружать предметы и рецепты для ИИ при старте сервера и после /reload. */
	public boolean export = true;

	/** brain запускается сервером как дочерний процесс и останавливается вместе с ним. */
	public static final class Brain {
		public boolean autostart = true;
		/** Папка brain/ из репозитория. Пусто — автозапуск выключен. */
		public String dir = "";
		/** Команда запуска; к ней добавляются --server-dir и --exit-on-stdin-eof. */
		public List<String> command = new ArrayList<>(List.of("uv", "run", "modpack-brain", "run"));
	}

	public static final class Telegram {
		public String token = "";
		public List<Long> allowedChatIds = new ArrayList<>();
		/** Куда слать события сервера; null — первый из allowedChatIds. */
		public Long eventsChatId;
	}

	public static final class Llm {
		/** sonnet | opus | haiku или полный id модели. */
		public String model = "sonnet";
		public int maxTurns = 30;
		public int timeoutSeconds = 240;
		public int questionsPerUserPerDay = 50;
	}

	public static final class Events {
		public boolean server = true;
		public boolean joinLeave = true;
		public boolean death = true;
		public boolean advancement = true;
		public boolean chat = true;
	}

	public static BridgeConfig loadOrCreate(Path path) throws IOException {
		BridgeConfig config = null;
		if (Files.exists(path)) {
			try {
				config = GSON.fromJson(Files.readString(path, StandardCharsets.UTF_8), BridgeConfig.class);
			} catch (JsonParseException e) {
				throw new IOException("cannot parse " + path + ": " + e.getMessage(), e);
			}
		}
		if (config == null) {
			config = new BridgeConfig();
		}
		if (config.brain == null) {
			config.brain = new Brain();
		}
		if (config.telegram == null) {
			config.telegram = new Telegram();
		}
		if (config.llm == null) {
			config.llm = new Llm();
		}
		if (config.events == null) {
			config.events = new Events();
		}
		if (config.token == null || config.token.isBlank()) {
			config.token = newToken();
		}
		// Перезаписываем всегда: так в файле появляются новые поля после обновления мода.
		Files.createDirectories(path.getParent());
		Files.writeString(path, GSON.toJson(config), StandardCharsets.UTF_8);
		return config;
	}

	static String newToken() {
		byte[] bytes = new byte[32];
		new SecureRandom().nextBytes(bytes);
		return HexFormat.of().formatHex(bytes);
	}
}
