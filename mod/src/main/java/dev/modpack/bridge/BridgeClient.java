package dev.modpack.bridge;

import com.google.gson.JsonObject;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * WebSocket-клиент к brain. Весь сетевой код — в своём потоке: серверный поток только кладёт сообщения в очередь.
 * Пока brain недоступен, последние {@link #QUEUE_LIMIT} сообщений ждут в очереди, остальное отбрасывается.
 */
public final class BridgeClient {
	static final int QUEUE_LIMIT = 100;
	private static final Logger LOG = LoggerFactory.getLogger("modpack_bridge");
	private static final long MAX_BACKOFF_SECONDS = 30;

	private final URI uri;
	private final String token;
	private final String modVersion;
	private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
	private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(r -> {
		Thread thread = new Thread(r, "modpack-bridge");
		thread.setDaemon(true);
		return thread;
	});
	// Доступ только из потока executor.
	private final Deque<String> queue = new ArrayDeque<>();
	private WebSocket socket;
	private boolean connecting;
	private boolean closed;
	private long backoffSeconds = 1;
	private boolean warnedOffline;

	public BridgeClient(URI uri, String token, String modVersion) {
		this.uri = uri;
		this.token = token;
		this.modVersion = modVersion;
	}

	public void start() {
		executor.execute(this::connect);
	}

	/** Потокобезопасно, не блокирует. */
	public void send(JsonObject message) {
		if (executor.isShutdown()) {
			return;
		}
		String text = message.toString();
		executor.execute(() -> {
			queue.addLast(text);
			while (queue.size() > QUEUE_LIMIT) {
				queue.removeFirst();
			}
			flush();
		});
	}

	/** Отправить то, что в очереди (до timeout), и закрыть соединение. */
	public void shutdown(Duration timeout) {
		executor.execute(() -> {
			closed = true;
			flush();
			if (socket != null) {
				socket.sendClose(WebSocket.NORMAL_CLOSURE, "server stopping");
			}
		});
		executor.shutdown();
		try {
			executor.awaitTermination(timeout.toMillis(), TimeUnit.MILLISECONDS);
		} catch (InterruptedException e) {
			Thread.currentThread().interrupt();
		}
	}

	private void connect() {
		if (closed || socket != null || connecting) {
			return;
		}
		connecting = true;
		http.newWebSocketBuilder()
				.header("Authorization", "Bearer " + token)
				.connectTimeout(Duration.ofSeconds(5))
				.buildAsync(uri, new Listener())
				.whenCompleteAsync((ws, error) -> {
					connecting = false;
					if (error != null) {
						if (!warnedOffline) {
							LOG.warn("brain is unavailable ({}): {}. Will keep reconnecting.", uri, rootMessage(error));
							warnedOffline = true;
						}
						scheduleReconnect();
						return;
					}
					LOG.info("connected to brain {}", uri);
					socket = ws;
					backoffSeconds = 1;
					warnedOffline = false;
					JsonObject hello = new JsonObject();
					hello.addProperty("type", "hello");
					hello.addProperty("mod_version", modVersion);
					queue.addFirst(hello.toString());
					flush();
				}, executor);
	}

	private void flush() {
		while (socket != null && !queue.isEmpty()) {
			String text = queue.peekFirst();
			try {
				// Ждём отправки: WebSocket не допускает параллельных sendText.
				socket.sendText(text, true).get(10, TimeUnit.SECONDS);
				queue.removeFirst();
			} catch (Exception e) {
				LOG.warn("failed to send to brain: {}", rootMessage(e));
				dropSocket();
			}
		}
	}

	private void dropSocket() {
		if (socket != null) {
			socket.abort();
			socket = null;
		}
		scheduleReconnect();
	}

	private void scheduleReconnect() {
		if (closed || executor.isShutdown()) {
			return;
		}
		long delay = backoffSeconds;
		backoffSeconds = Math.min(backoffSeconds * 2, MAX_BACKOFF_SECONDS);
		executor.schedule(this::connect, delay, TimeUnit.SECONDS);
	}

	private static String rootMessage(Throwable error) {
		Throwable root = error;
		while (root.getCause() != null) {
			root = root.getCause();
		}
		return root.getClass().getSimpleName() + (root.getMessage() != null ? ": " + root.getMessage() : "");
	}

	private final class Listener implements WebSocket.Listener {
		private final StringBuilder partial = new StringBuilder();

		@Override
		public CompletionStage<?> onText(WebSocket ws, CharSequence data, boolean last) {
			partial.append(data);
			if (last) {
				String message = partial.toString();
				partial.setLength(0);
				// Команды от brain (мост чата, /online) появятся в M4.
				LOG.debug("from brain: {}", message);
			}
			ws.request(1);
			return null;
		}

		@Override
		public CompletionStage<?> onClose(WebSocket ws, int statusCode, String reason) {
			executor.execute(() -> {
				if (socket == ws) {
					LOG.info("brain closed the connection ({} {})", statusCode, reason);
					socket = null;
					scheduleReconnect();
				}
			});
			return null;
		}

		@Override
		public void onError(WebSocket ws, Throwable error) {
			executor.execute(() -> {
				if (socket == ws) {
					LOG.warn("brain connection error: {}", rootMessage(error));
					socket = null;
					scheduleReconnect();
				}
			});
		}
	}
}
