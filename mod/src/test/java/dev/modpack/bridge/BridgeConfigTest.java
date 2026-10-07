package dev.modpack.bridge;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BridgeConfigTest {
	@Test
	void createsConfigWithRandomToken(@TempDir Path dir) throws Exception {
		Path path = dir.resolve("config/modpack-bridge.json");
		BridgeConfig config = BridgeConfig.loadOrCreate(path);
		assertEquals(64, config.token.length());
		assertTrue(Files.readString(path).contains(config.token));
		assertEquals(config.token, BridgeConfig.loadOrCreate(path).token);
	}

	@Test
	void keepsUserValuesAndFillsMissingFields(@TempDir Path dir) throws Exception {
		Path path = dir.resolve("modpack-bridge.json");
		Files.writeString(path, "{\"url\": \"ws://127.0.0.1:9000\", \"token\": \"t\", \"events\": {\"chat\": false}}",
				StandardCharsets.UTF_8);
		BridgeConfig config = BridgeConfig.loadOrCreate(path);
		assertEquals("ws://127.0.0.1:9000", config.url);
		assertEquals("t", config.token);
		assertFalse(config.events.chat);
		assertTrue(config.events.death);
		assertTrue(Files.readString(path).contains("joinLeave"));
	}

	@Test
	void keepsStatusSectionOfOlderTelegramConfig(@TempDir Path dir) throws Exception {
		Path path = dir.resolve("modpack-bridge.json");
		Files.writeString(path, "{\"telegram\": {\"token\": \"x\"}}", StandardCharsets.UTF_8);
		assertTrue(BridgeConfig.loadOrCreate(path).telegram.status.pinned);
		Files.writeString(path, "{\"telegram\": {\"status\": {\"panelUrl\": \"https://example.com\", \"pinned\": false}}}",
				StandardCharsets.UTF_8);
		BridgeConfig config = BridgeConfig.loadOrCreate(path);
		assertEquals("https://example.com", config.telegram.status.panelUrl);
		assertFalse(config.telegram.status.pinned);
		assertTrue(Files.readString(path).contains("\"address\""));
	}
}
