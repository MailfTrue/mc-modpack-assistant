package dev.modpack.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParseException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.HexFormat;

/**
 * config/modpack-bridge.json. При первом запуске создаётся с новым случайным токеном,
 * brain читает тот же файл, так что руками ничего копировать не нужно.
 */
public final class BridgeConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();

	public String url = "ws://127.0.0.1:8765";
	public String token = "";
	public Events events = new Events();

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
