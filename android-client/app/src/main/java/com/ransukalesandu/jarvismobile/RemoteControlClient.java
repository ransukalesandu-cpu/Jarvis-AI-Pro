package com.ransukalesandu.jarvismobile;

import org.json.JSONObject;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/**
 * Remote control and event feed for JARVIS Mobile.
 *
 * All microphone capture and speaker playback remain on the JARVIS desktop.
 * This client only sends typed commands and receives status/transcript events.
 */
final class RemoteControlClient {
    interface Listener {
        void onConnected();
        void onDisconnected(String reason);
        void onEvent(JSONObject event);
        void onError(String message);
    }

    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
    private static final int MAX_COMMAND_LENGTH = 4000;

    private final OkHttpClient httpClient = new OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .retryOnConnectionFailure(true)
            .build();
    private final ScheduledExecutorService networkExecutor =
            Executors.newSingleThreadScheduledExecutor();
    private final AtomicBoolean active = new AtomicBoolean(false);
    private final AtomicBoolean reconnectScheduled = new AtomicBoolean(false);

    private volatile String baseUrl = "";
    private volatile String deviceToken = "";
    private volatile String sessionToken = "";
    private volatile WebSocket webSocket;
    private volatile Listener listener;
    private int reconnectAttempt = 0;

    void connect(String rootUrl, String token, Listener callbacks) {
        disconnect();
        if (rootUrl == null || token == null || token.isEmpty()) {
            callbacks.onError("Pair this tablet before connecting.");
            return;
        }
        baseUrl = rootUrl.replaceAll("/+$", "");
        deviceToken = token;
        listener = callbacks;
        active.set(true);
        reconnectAttempt = 0;
        networkExecutor.execute(this::openSession);
    }

    private void openSession() {
        if (!active.get()) return;
        try {
            String bearer = requestSessionToken();
            if (!active.get()) return;
            sessionToken = bearer;
            String wsUrl = baseUrl.replaceFirst("^https://", "wss://")
                    + "/ws?token="
                    + URLEncoder.encode(bearer, StandardCharsets.UTF_8.name());
            Request request = new Request.Builder().url(wsUrl).build();
            webSocket = httpClient.newWebSocket(request, new WebSocketListener() {
                @Override
                public void onOpen(WebSocket socket, Response response) {
                    if (!active.get()) {
                        socket.close(1000, "Remote control stopped");
                        return;
                    }
                    webSocket = socket;
                    reconnectAttempt = 0;
                    reconnectScheduled.set(false);
                    notifyConnected();
                }

                @Override
                public void onMessage(WebSocket socket, String text) {
                    if (!active.get()) return;
                    try {
                        JSONObject event = new JSONObject(text);
                        Listener current = listener;
                        if (current != null) current.onEvent(event);
                    } catch (Exception ignored) {
                        // Ignore malformed messages, but keep the remote connection alive.
                    }
                }

                @Override
                public void onMessage(WebSocket socket, ByteString bytes) {
                    // This endpoint is JSON-only. Ignore any binary frame.
                }

                @Override
                public void onClosing(WebSocket socket, int code, String reason) {
                    socket.close(code, reason);
                }

                @Override
                public void onClosed(WebSocket socket, int code, String reason) {
                    if (webSocket == socket) webSocket = null;
                    handleDisconnect("Desktop connection closed.");
                }

                @Override
                public void onFailure(WebSocket socket, Throwable error, Response response) {
                    if (webSocket == socket) webSocket = null;
                    handleDisconnect("Connection lost. Trying to reconnect…");
                }
            });
        } catch (ExpiredDeviceException error) {
            active.set(false);
            notifyError("This pairing has expired or was revoked. Pair the tablet again.");
            notifyDisconnected("Pairing expired.");
        } catch (Exception error) {
            if (active.get()) {
                notifyError("Could not connect: " + safeMessage(error));
                scheduleReconnect();
            }
        }
    }

    private String requestSessionToken() throws Exception {
        JSONObject payload = new JSONObject();
        payload.put("device_token", deviceToken);
        RequestBody body = RequestBody.create(JSON, payload.toString());
        Request request = new Request.Builder()
                .url(baseUrl + "/api/device-login")
                .post(body)
                .header("Cache-Control", "no-store")
                .build();
        try (Response response = httpClient.newCall(request).execute()) {
            String raw = response.body() == null ? "{}" : response.body().string();
            JSONObject result = new JSONObject(raw);
            if (response.code() == 401) throw new ExpiredDeviceException();
            if (!response.isSuccessful() || !result.optBoolean("ok")) {
                throw new IOException(result.optString("error", "Device login was rejected."));
            }
            String token = result.optString("token", "");
            if (token.isEmpty()) throw new IOException("No session token was returned.");
            return token;
        }
    }

    boolean sendCommand(String command) {
        String text = command == null ? "" : command.trim();
        WebSocket socket = webSocket;
        if (!active.get() || socket == null || text.isEmpty()
                || text.length() > MAX_COMMAND_LENGTH) return false;
        try {
            JSONObject payload = new JSONObject();
            payload.put("type", "command");
            payload.put("text", text);
            return socket.send(payload.toString());
        } catch (Exception ignored) {
            return false;
        }
    }

    private void handleDisconnect(String reason) {
        if (!active.get()) return;
        notifyDisconnected(reason);
        scheduleReconnect();
    }

    private void scheduleReconnect() {
        if (!active.get() || !reconnectScheduled.compareAndSet(false, true)) return;
        reconnectAttempt = Math.min(reconnectAttempt + 1, 6);
        long delay = Math.min(30L, 1L << Math.min(reconnectAttempt - 1, 5));
        networkExecutor.schedule(() -> {
            reconnectScheduled.set(false);
            if (active.get() && webSocket == null) openSession();
        }, delay, TimeUnit.SECONDS);
    }

    private void notifyConnected() {
        Listener current = listener;
        if (current != null) current.onConnected();
    }

    private void notifyDisconnected(String reason) {
        Listener current = listener;
        if (current != null) current.onDisconnected(reason);
    }

    private void notifyError(String message) {
        Listener current = listener;
        if (current != null) current.onError(message);
    }

    private String safeMessage(Throwable error) {
        String message = error == null ? null : error.getMessage();
        return message == null || message.trim().isEmpty()
                ? "unknown error" : message.replaceAll("[\\r\\n]+", " ").trim();
    }

    void disconnect() {
        active.set(false);
        reconnectScheduled.set(false);
        WebSocket socket = webSocket;
        webSocket = null;
        if (socket != null) socket.close(1000, "Remote control stopped");
        sessionToken = "";
    }

    void shutdown() {
        disconnect();
        networkExecutor.shutdownNow();
        httpClient.dispatcher().cancelAll();
        httpClient.connectionPool().evictAll();
    }

    private static final class ExpiredDeviceException extends IOException {
        ExpiredDeviceException() {
            super("The device token is expired.");
        }
    }
}
