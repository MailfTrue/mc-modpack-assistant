package dev.modpack.bridge;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * brain как дочерний процесс сервера. Живёт, пока жив сервер:
 * при остановке закрываем его stdin (brain сам корректно завершается), а если сервер упал —
 * stdin закрывает ОС, и brain тоже выходит. Вывод — в logs/modpack-brain.log.
 *
 * Если brain завершился сам (упал или его остановили при деплое, чтобы подхватить новый код),
 * мод запускает его снова: через 3 с, при повторных падениях — с паузой до 5 минут.
 */
public final class BrainProcess {
	private static final Logger LOG = LoggerFactory.getLogger("modpack_bridge");

	private final List<String> command;
	private final Path dir;
	private final Path log;
	private Process process;
	private OutputStream stdin;
	private volatile boolean stopping;
	private long startedAt;
	private long restartDelayMs = MIN_RESTART_DELAY_MS;

	private static final long MIN_RESTART_DELAY_MS = 3_000;
	private static final long MAX_RESTART_DELAY_MS = 5 * 60_000;
	/** Проработал дольше — считаем, что это не цикл падений, и пауза снова минимальная. */
	private static final long STABLE_RUN_MS = 10 * 60_000;

	private BrainProcess(List<String> command, Path dir, Path log) {
		this.command = command;
		this.dir = dir;
		this.log = log;
	}

	/** null, если автозапуск выключен или настроен неверно (причина уже в логе). */
	public static BrainProcess fromConfig(BridgeConfig.Brain config, Path serverDir) {
		if (!config.autostart) {
			LOG.info("brain autostart is disabled in config");
			return null;
		}
		if (config.dir == null || config.dir.isBlank()) {
			LOG.warn("brain autostart: set brain.dir in config/modpack-bridge.json to the repo's brain folder");
			return null;
		}
		Path dir = Path.of(config.dir).toAbsolutePath().normalize();
		if (!Files.isDirectory(dir)) {
			LOG.error("brain autostart: folder not found: {}", dir);
			return null;
		}
		if (config.command == null || config.command.isEmpty()) {
			LOG.error("brain autostart: brain.command is empty");
			return null;
		}
		List<String> command = new ArrayList<>(config.command);
		command.add("--server-dir");
		command.add(serverDir.toAbsolutePath().normalize().toString());
		command.add("--exit-on-stdin-eof");
		return new BrainProcess(command, dir, serverDir.resolve("logs").resolve("modpack-brain.log"));
	}

	public synchronized void start() {
		if (stopping) {
			return;
		}
		try {
			Files.createDirectories(log.getParent());
			ProcessBuilder builder = new ProcessBuilder(command)
					.directory(dir.toFile())
					.redirectErrorStream(true)
					.redirectOutput(ProcessBuilder.Redirect.appendTo(log.toFile()));
			builder.environment().put("PYTHONIOENCODING", "utf-8");
			process = builder.start();
			stdin = process.getOutputStream();
		} catch (IOException e) {
			LOG.error("cannot start brain ({} in {}): {}", String.join(" ", command), dir, e.getMessage());
			scheduleRestart();
			return;
		}
		startedAt = System.currentTimeMillis();
		LOG.info("brain started (pid {}), log: {}", process.pid(), log);
		process.onExit().thenAccept(p -> {
			if (!stopping) {
				LOG.warn("brain exited with code {}, see {}", p.exitValue(), log);
				scheduleRestart();
			}
		});
	}

	private synchronized void scheduleRestart() {
		if (stopping) {
			return;
		}
		if (System.currentTimeMillis() - startedAt > STABLE_RUN_MS) {
			restartDelayMs = MIN_RESTART_DELAY_MS;
		}
		long delay = restartDelayMs;
		restartDelayMs = Math.min(restartDelayMs * 2, MAX_RESTART_DELAY_MS);
		LOG.info("restarting brain in {} s", delay / 1000);
		CompletableFuture.delayedExecutor(delay, TimeUnit.MILLISECONDS).execute(this::start);
	}

	public void stop() {
		stopping = true;
		if (process == null || !process.isAlive()) {
			return;
		}
		try {
			stdin.close();
		} catch (IOException ignored) {
			// процесс уже закрыл свой конец
		}
		try {
			if (process.waitFor(8, TimeUnit.SECONDS)) {
				LOG.info("brain stopped");
				return;
			}
		} catch (InterruptedException e) {
			Thread.currentThread().interrupt();
		}
		LOG.warn("brain did not stop in time, killing it");
		process.descendants().forEach(ProcessHandle::destroyForcibly);
		process.destroyForcibly();
	}
}
