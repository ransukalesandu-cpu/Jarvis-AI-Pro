package com.ransukalesandu.jarvismobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.NoiseSuppressor;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
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
 * Runs the live tablet voice connection in a visible microphone foreground service.
 *
 * Input to JARVIS: 16 kHz, mono, signed 16-bit PCM.
 * JARVIS output:     24 kHz, mono, signed 16-bit PCM.
 */
public final class AudioBridgeService extends Service {
    static final String ACTION_START = "com.ransukalesandu.jarvismobile.START_VOICE";
    static final String ACTION_STATUS = "com.ransukalesandu.jarvismobile.VOICE_STATUS";
    static final String ACTION_LEVEL = "com.ransukalesandu.jarvismobile.MIC_LEVEL";
    static final String EXTRA_BASE_URL = "base_url";
    static final String EXTRA_DEVICE_TOKEN = "device_token";
    static final String EXTRA_STATUS = "status";
    static final String EXTRA_ACTIVE = "active";
    static final String EXTRA_CONNECTED = "connected";
    static final String EXTRA_LEVEL = "level";

    private static final String CHANNEL_ID = "jarvis_voice_bridge";
    private static final int NOTIFICATION_ID = 3107;
    private static final int INPUT_SAMPLE_RATE = 16_000;
    private static final int OUTPUT_SAMPLE_RATE = 24_000;
    private static final int INPUT_FRAME_BYTES = 640; // 20 ms at 16 kHz mono PCM16
    private static final int MAX_SOCKET_QUEUE_BYTES = 256 * 1024;
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");

    private final AtomicBoolean captureActive = new AtomicBoolean(false);
    private final AtomicBoolean reconnectScheduled = new AtomicBoolean(false);
    private final ExecutorService captureExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService playbackExecutor = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService networkExecutor = Executors.newSingleThreadScheduledExecutor();

    private volatile boolean running = false;
    private volatile boolean connected = false;
    private volatile boolean authenticationFailed = false;
    private volatile String baseUrl = "";
    private volatile String deviceToken = "";
    private volatile AudioRecord recorder;
    private volatile AudioTrack player;
    private volatile WebSocket socket;
    private volatile AcousticEchoCanceler echoCanceler;
    private volatile NoiseSuppressor noiseSuppressor;

    private OkHttpClient client;
    private int reconnectAttempt = 0;

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        client = new OkHttpClient.Builder()
                .pingInterval(20, TimeUnit.SECONDS)
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .retryOnConnectionFailure(true)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || !ACTION_START.equals(intent.getAction())) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (running) {
            report("Tablet voice bridge is already running.", connected);
            return START_STICKY;
        }

        String requestedUrl = intent.getStringExtra(EXTRA_BASE_URL);
        String requestedToken = intent.getStringExtra(EXTRA_DEVICE_TOKEN);
        if (requestedUrl == null || requestedToken == null || requestedToken.isEmpty()) {
            report("Pair this tablet with JARVIS before starting voice.", false);
            stopSelf(startId);
            return START_NOT_STICKY;
        }

        baseUrl = requestedUrl.replaceAll("/+$", "");
        deviceToken = requestedToken;
        running = true;
        authenticationFailed = false;
        startForeground(NOTIFICATION_ID, buildNotification());
        try {
            preparePlayer();
        } catch (Exception error) {
            report("Could not open tablet speaker: " + safeMessage(error), false);
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        report("Connecting securely to your JARVIS desktop…", false);
        networkExecutor.execute(this::connectToDesktop);
        return START_STICKY;
    }

    private void connectToDesktop() {
        if (!running || authenticationFailed) return;
        try {
            String sessionToken = requestSessionToken();
            if (!running) return;
            String wsUrl = baseUrl.replaceFirst("^https://", "wss://")
                    + "/ws/phone-audio?token="
                    + URLEncoder.encode(sessionToken, StandardCharsets.UTF_8.name());
            Request request = new Request.Builder().url(wsUrl).build();
            socket = client.newWebSocket(request, new WebSocketListener() {
                @Override
                public void onOpen(WebSocket webSocket, Response response) {
                    if (!running) {
                        webSocket.close(1000, "Voice bridge stopped");
                        return;
                    }
                    socket = webSocket;
                    connected = true;
                    reconnectAttempt = 0;
                    reconnectScheduled.set(false);
                    report("Connected. Speak naturally to JARVIS through the tablet.", true);
                    startCapture();
                }

                @Override
                public void onMessage(WebSocket webSocket, ByteString bytes) {
                    if (running && bytes.size() > 0) {
                        byte[] pcm = bytes.toByteArray();
                        playbackExecutor.execute(() -> playPcm(pcm));
                    }
                }

                @Override
                public void onClosing(WebSocket webSocket, int code, String reason) {
                    webSocket.close(code, reason);
                }

                @Override
                public void onClosed(WebSocket webSocket, int code, String reason) {
                    handleSocketEnded(webSocket, "Voice connection closed.");
                }

                @Override
                public void onFailure(WebSocket webSocket, Throwable error, Response response) {
                    handleSocketEnded(webSocket, "Connection lost; reconnecting automatically.");
                }
            });
        } catch (Exception error) {
            if (!running) return;
            report("Could not connect: " + safeMessage(error), false);
            scheduleReconnect();
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

        try (Response response = client.newCall(request).execute()) {
            String raw = response.body() == null ? "{}" : response.body().string();
            JSONObject result = new JSONObject(raw);
            if (response.code() == 401) {
                authenticationFailed = true;
                throw new PairingExpiredException();
            }
            if (!response.isSuccessful() || !result.optBoolean("ok")) {
                throw new IOException(result.optString("error", "Device login was rejected."));
            }
            String token = result.optString("token", "");
            if (token.isEmpty()) throw new IOException("The server did not return a session token.");
            return token;
        }
    }

    private void handleSocketEnded(WebSocket endedSocket, String message) {
        if (socket == endedSocket) socket = null;
        connected = false;
        stopCapture();
        if (!running) return;
        if (authenticationFailed) {
            report("Pairing expired. Pair this tablet with JARVIS again.", false);
            stopSelf();
            return;
        }
        report(message, false);
        scheduleReconnect();
    }

    private void scheduleReconnect() {
        if (!running || authenticationFailed || !reconnectScheduled.compareAndSet(false, true)) return;
        reconnectAttempt = Math.min(reconnectAttempt + 1, 6);
        long delaySeconds = Math.min(30, 1L << Math.min(reconnectAttempt - 1, 5));
        networkExecutor.schedule(() -> {
            reconnectScheduled.set(false);
            if (running && !connected) connectToDesktop();
        }, delaySeconds, TimeUnit.SECONDS);
    }

    private void preparePlayer() {
        if (player != null && player.getState() == AudioTrack.STATE_INITIALIZED) return;
        int minimum = AudioTrack.getMinBufferSize(
                OUTPUT_SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IllegalStateException("The tablet does not support 24 kHz PCM playback.");
        int bufferSize = Math.max(minimum, 24_000 * 2 / 2);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioAttributes attributes = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build();
            AudioFormat format = new AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(OUTPUT_SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build();
            player = new AudioTrack.Builder()
                    .setAudioAttributes(attributes)
                    .setAudioFormat(format)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .setBufferSizeInBytes(bufferSize)
                    .build();
        } else {
            player = new AudioTrack(AudioManager.STREAM_MUSIC, OUTPUT_SAMPLE_RATE,
                    AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    bufferSize, AudioTrack.MODE_STREAM);
        }
        if (player.getState() != AudioTrack.STATE_INITIALIZED) {
            player.release();
            player = null;
            throw new IllegalStateException("The tablet speaker could not be initialized.");
        }
        player.play();
    }

    private void playPcm(byte[] pcm) {
        AudioTrack track = player;
        if (!running || track == null || track.getState() != AudioTrack.STATE_INITIALIZED) return;
        try {
            int aligned = pcm.length & ~1;
            int offset = 0;
            while (running && offset < aligned) {
                int written = track.write(pcm, offset, aligned - offset, AudioTrack.WRITE_BLOCKING);
                if (written < 0) {
                    report("Tablet speaker playback failed (" + written + ").", connected);
                    return;
                }
                if (written == 0) break;
                offset += written;
            }
        } catch (Exception error) {
            report("Tablet speaker playback failed: " + safeMessage(error), connected);
        }
    }

    private void startCapture() {
        if (!running || !connected || !captureActive.compareAndSet(false, true)) return;
        captureExecutor.execute(() -> {
            AudioRecord local = null;
            try {
                int minimum = AudioRecord.getMinBufferSize(
                        INPUT_SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT);
                if (minimum <= 0) throw new IllegalStateException("The tablet microphone does not support 16 kHz PCM.");
                int bufferSize = Math.max(minimum, INPUT_FRAME_BYTES * 6);
                local = new AudioRecord(
                        MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                        INPUT_SAMPLE_RATE,
                        AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT,
                        bufferSize);
                if (local.getState() != AudioRecord.STATE_INITIALIZED) {
                    throw new IllegalStateException("The tablet microphone could not be initialized.");
                }
                recorder = local;
                enableVoiceProcessing(local);
                local.startRecording();

                byte[] frame = new byte[INPUT_FRAME_BYTES];
                long lastLevelReport = 0L;
                while (running && connected && captureActive.get()) {
                    int count = local.read(frame, 0, frame.length, AudioRecord.READ_BLOCKING);
                    if (count == AudioRecord.ERROR_DEAD_OBJECT || count == AudioRecord.ERROR_INVALID_OPERATION) {
                        throw new IOException("The microphone stream ended.");
                    }
                    if (count <= 0) continue;
                    int aligned = count & ~1;
                    if (aligned == 0) continue;

                    WebSocket activeSocket = socket;
                    if (activeSocket != null && connected && activeSocket.queueSize() < MAX_SOCKET_QUEUE_BYTES) {
                        activeSocket.send(ByteString.of(Arrays.copyOf(frame, aligned)));
                    }

                    long now = SystemClock.elapsedRealtime();
                    if (now - lastLevelReport >= 140L) {
                        postMicLevel(frame, aligned);
                        lastLevelReport = now;
                    }
                }
            } catch (Exception error) {
                if (running && connected) report("Microphone issue: " + safeMessage(error), true);
            } finally {
                captureActive.set(false);
                releaseVoiceProcessing();
                if (local != null) {
                    try {
                        if (local.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) local.stop();
                    } catch (Exception ignored) {
                    }
                    local.release();
                }
                if (recorder == local) recorder = null;
            }
        });
    }

    private void enableVoiceProcessing(AudioRecord record) {
        try {
            if (AcousticEchoCanceler.isAvailable()) {
                echoCanceler = AcousticEchoCanceler.create(record.getAudioSessionId());
                if (echoCanceler != null) echoCanceler.setEnabled(true);
            }
        } catch (Exception ignored) {
            echoCanceler = null;
        }
        try {
            if (NoiseSuppressor.isAvailable()) {
                noiseSuppressor = NoiseSuppressor.create(record.getAudioSessionId());
                if (noiseSuppressor != null) noiseSuppressor.setEnabled(true);
            }
        } catch (Exception ignored) {
            noiseSuppressor = null;
        }
    }

    private void releaseVoiceProcessing() {
        AcousticEchoCanceler echo = echoCanceler;
        echoCanceler = null;
        if (echo != null) {
            try { echo.release(); } catch (Exception ignored) {}
        }
        NoiseSuppressor suppressor = noiseSuppressor;
        noiseSuppressor = null;
        if (suppressor != null) {
            try { suppressor.release(); } catch (Exception ignored) {}
        }
    }

    private void stopCapture() {
        captureActive.set(false);
        AudioRecord current = recorder;
        if (current != null) {
            try {
                if (current.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) current.stop();
            } catch (Exception ignored) {
            }
        }
    }

    private void postMicLevel(byte[] data, int length) {
        long sumSquares = 0L;
        int samples = length / 2;
        for (int i = 0; i + 1 < length; i += 2) {
            int raw = (data[i] & 0xff) | (data[i + 1] << 8);
            short sample = (short) raw;
            sumSquares += (long) sample * sample;
        }
        if (samples == 0) return;
        double rms = Math.sqrt((double) sumSquares / samples);
        float level = (float) Math.min(1.0, rms / 9000.0);
        Intent intent = new Intent(ACTION_LEVEL).setPackage(getPackageName());
        intent.putExtra(EXTRA_LEVEL, level);
        sendBroadcast(intent);
    }

    private void report(String message, boolean isConnected) {
        Intent intent = new Intent(ACTION_STATUS).setPackage(getPackageName());
        intent.putExtra(EXTRA_STATUS, message);
        intent.putExtra(EXTRA_ACTIVE, running);
        intent.putExtra(EXTRA_CONNECTED, isConnected);
        sendBroadcast(intent);
        if (running) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.notify(NOTIFICATION_ID, buildNotification());
        }
    }

    private Notification buildNotification() {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("JARVIS tablet voice bridge")
                .setContentText(connected
                        ? "Microphone connected — tap the app to stop voice."
                        : "Connecting or reconnecting to your private desktop.")
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(NotificationCompat.CATEGORY_SERVICE)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "JARVIS voice bridge", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Visible notification while the tablet microphone is streamed to JARVIS.");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private String safeMessage(Throwable error) {
        String message = error == null ? null : error.getMessage();
        return message == null || message.trim().isEmpty()
                ? "unknown error" : message.replaceAll("[\\r\\n]+", " ").trim();
    }

    @Override
    public void onDestroy() {
        running = false;
        connected = false;
        report("Tablet voice bridge stopped.", false);
        WebSocket currentSocket = socket;
        socket = null;
        if (currentSocket != null) {
            try { currentSocket.close(1000, "Voice bridge stopped"); } catch (Exception ignored) {}
        }
        stopCapture();
        AudioTrack track = player;
        player = null;
        if (track != null) {
            try { track.pause(); } catch (Exception ignored) {}
            try { track.flush(); } catch (Exception ignored) {}
            try { track.stop(); } catch (Exception ignored) {}
            track.release();
        }
        if (client != null) {
            try { client.dispatcher().cancelAll(); } catch (Exception ignored) {}
            try { client.connectionPool().evictAll(); } catch (Exception ignored) {}
        }
        captureExecutor.shutdownNow();
        playbackExecutor.shutdownNow();
        networkExecutor.shutdownNow();
        super.onDestroy();
    }

    private static final class PairingExpiredException extends IOException {
        PairingExpiredException() {
            super("The paired device token has expired.");
        }
    }
}
