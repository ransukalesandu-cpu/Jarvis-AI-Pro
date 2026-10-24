package com.ransukalesandu.jarvismobile;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.ContextCompat;

import org.json.JSONObject;

import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

public final class MainActivity extends Activity {
    private static final int REQUEST_PERMISSIONS = 1201;
    private static final String PREFS = "jarvis_mobile_settings";
    private static final String PREF_BASE_URL = "base_url";
    private static final String ACTION_STATUS = AudioBridgeService.ACTION_STATUS;
    private static final String ACTION_LEVEL = AudioBridgeService.ACTION_LEVEL;

    private final ExecutorService pairingExecutor = Executors.newSingleThreadExecutor();
    private final OkHttpClient httpClient = new OkHttpClient.Builder().build();

    private EditText endpointInput;
    private EditText pinInput;
    private TextView statusText;
    private TextView pairedText;
    private Button pairButton;
    private Button voiceButton;
    private HudOrbView orbView;

    private String baseUrl = "";
    private String deviceToken = "";
    private boolean voiceActive = false;
    private boolean pendingStart = false;
    private boolean receiverRegistered = false;

    private final BroadcastReceiver bridgeReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null) return;
            if (ACTION_STATUS.equals(intent.getAction())) {
                String message = intent.getStringExtra(AudioBridgeService.EXTRA_STATUS);
                voiceActive = intent.getBooleanExtra(AudioBridgeService.EXTRA_ACTIVE, false);
                boolean connected = intent.getBooleanExtra(AudioBridgeService.EXTRA_CONNECTED, false);
                if (message != null) statusText.setText(message);
                orbView.setActive(connected);
                updateButtons();
            } else if (ACTION_LEVEL.equals(intent.getAction())) {
                orbView.setLevel(intent.getFloatExtra(AudioBridgeService.EXTRA_LEVEL, 0f));
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.rgb(6, 10, 18));
        getWindow().setNavigationBarColor(Color.rgb(6, 10, 18));
        buildUi();
        loadSavedPairing();
        registerBridgeReceiver();
        updateButtons();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(6, 10, 18));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(24), dp(24), dp(24), dp(28));

        TextView brand = new TextView(this);
        brand.setText("J.A.R.V.I.S");
        brand.setTextColor(Color.rgb(92, 242, 255));
        brand.setTextSize(30);
        brand.setLetterSpacing(0.18f);
        brand.setGravity(Gravity.CENTER);
        brand.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.BOLD));
        root.addView(brand, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("MOBILE VOICE BRIDGE  /  SECURE LINK");
        subtitle.setTextColor(Color.rgb(121, 153, 177));
        subtitle.setTextSize(11);
        subtitle.setLetterSpacing(0.10f);
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subParams = matchWrap();
        subParams.topMargin = dp(5);
        root.addView(subtitle, subParams);

        orbView = new HudOrbView(this);
        LinearLayout.LayoutParams orbParams = new LinearLayout.LayoutParams(dp(248), dp(248));
        orbParams.gravity = Gravity.CENTER_HORIZONTAL;
        orbParams.topMargin = dp(8);
        orbParams.bottomMargin = dp(2);
        root.addView(orbView, orbParams);

        statusText = new TextView(this);
        statusText.setText("Enter your private JARVIS URL and pair code.");
        statusText.setTextColor(Color.rgb(210, 224, 237));
        statusText.setTextSize(14);
        statusText.setGravity(Gravity.CENTER);
        statusText.setMinHeight(dp(42));
        root.addView(statusText, matchWrap());

        pairedText = new TextView(this);
        pairedText.setText("NOT PAIRED");
        pairedText.setTextColor(Color.rgb(255, 193, 105));
        pairedText.setTextSize(11);
        pairedText.setLetterSpacing(0.12f);
        pairedText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams pairedParams = matchWrap();
        pairedParams.topMargin = dp(2);
        pairedParams.bottomMargin = dp(18);
        root.addView(pairedText, pairedParams);

        TextView urlLabel = fieldLabel("PRIVATE DESKTOP URL");
        root.addView(urlLabel, matchWrap());
        endpointInput = new EditText(this);
        endpointInput.setSingleLine(true);
        endpointInput.setTextSize(14);
        endpointInput.setHint("https://your-pc.your-tailnet.ts.net");
        endpointInput.setHintTextColor(Color.rgb(95, 115, 135));
        endpointInput.setTextColor(Color.WHITE);
        endpointInput.setSelectAllOnFocus(false);
        endpointInput.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        endpointInput.setPadding(dp(14), dp(12), dp(14), dp(12));
        endpointInput.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(48, 90, 112)));
        LinearLayout.LayoutParams inputParams = matchWrap();
        inputParams.topMargin = dp(6);
        inputParams.bottomMargin = dp(12);
        root.addView(endpointInput, inputParams);

        TextView pinLabel = fieldLabel("ONE-TIME PAIRING CODE");
        root.addView(pinLabel, matchWrap());
        pinInput = new EditText(this);
        pinInput.setSingleLine(true);
        pinInput.setTextSize(18);
        pinInput.setGravity(Gravity.CENTER);
        pinInput.setHint("ABC234");
        pinInput.setHintTextColor(Color.rgb(95, 115, 135));
        pinInput.setTextColor(Color.WHITE);
        pinInput.setLetterSpacing(0.22f);
        pinInput.setFilters(new android.text.InputFilter[]{
                new android.text.InputFilter.LengthFilter(6),
                new android.text.InputFilter.AllCaps()
        });
        pinInput.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        pinInput.setPadding(dp(14), dp(10), dp(14), dp(10));
        pinInput.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(48, 90, 112)));
        LinearLayout.LayoutParams pinParams = matchWrap();
        pinParams.topMargin = dp(6);
        pinParams.bottomMargin = dp(14);
        root.addView(pinInput, pinParams);

        pairButton = makeButton("PAIR TABLET", false);
        root.addView(pairButton, fullWidthButton());
        pairButton.setOnClickListener(v -> pairDevice());

        voiceButton = makeButton("START VOICE", true);
        LinearLayout.LayoutParams voiceParams = fullWidthButton();
        voiceParams.topMargin = dp(10);
        root.addView(voiceButton, voiceParams);
        voiceButton.setOnClickListener(v -> toggleVoice());

        TextView privacy = new TextView(this);
        privacy.setText("Audio is streamed live to your paired desktop. Raw microphone audio is not saved by this app. Keep the tablet paired only with a desktop you trust.");
        privacy.setTextColor(Color.rgb(105, 129, 151));
        privacy.setTextSize(11);
        privacy.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams privacyParams = matchWrap();
        privacyParams.topMargin = dp(16);
        root.addView(privacy, privacyParams);

        scroll.addView(root);
        setContentView(scroll);
    }

    private TextView fieldLabel(String text) {
        TextView label = new TextView(this);
        label.setText(text);
        label.setTextColor(Color.rgb(125, 180, 201));
        label.setTextSize(11);
        label.setLetterSpacing(0.10f);
        return label;
    }

    private Button makeButton(String text, boolean primary) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(true);
        button.setTextSize(13);
        button.setLetterSpacing(0.06f);
        button.setTextColor(primary ? Color.rgb(3, 15, 25) : Color.rgb(92, 242, 255));
        button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                primary ? Color.rgb(92, 242, 255) : Color.rgb(15, 35, 50)));
        return button;
    }

    private LinearLayout.LayoutParams fullWidthButton() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(52));
        params.gravity = Gravity.CENTER_HORIZONTAL;
        return params;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void loadSavedPairing() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        baseUrl = prefs.getString(PREF_BASE_URL, "");
        if (!baseUrl.isEmpty()) endpointInput.setText(baseUrl);
        try {
            deviceToken = SecureTokenStore.getDeviceToken(this);
        } catch (Exception error) {
            deviceToken = "";
            statusText.setText("Secure token storage is unavailable. Pair this device again.");
        }
        if (!deviceToken.isEmpty()) {
            pairedText.setText("DEVICE PAIRED");
            pairedText.setTextColor(Color.rgb(92, 242, 255));
            statusText.setText("Paired device found. Tap START VOICE when ready.");
        }
    }

    private void registerBridgeReceiver() {
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_STATUS);
        filter.addAction(ACTION_LEVEL);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(bridgeReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(bridgeReceiver, filter);
        }
        receiverRegistered = true;
    }

    private String normalizeEndpoint() throws Exception {
        String candidate = endpointInput.getText().toString().trim();
        while (candidate.endsWith("/")) {
            candidate = candidate.substring(0, candidate.length() - 1);
        }
        URL url = new URL(candidate);
        if (!"https".equalsIgnoreCase(url.getProtocol())) {
            throw new IllegalArgumentException("Use the private HTTPS URL from Tailscale Serve.");
        }
        if (url.getHost() == null || url.getHost().isEmpty()
                || (url.getPath() != null && !url.getPath().isEmpty() && !"/".equals(url.getPath()))
                || url.getQuery() != null || url.getRef() != null
                || url.getUserInfo() != null) {
            throw new IllegalArgumentException("Enter the root URL only, without a path or query.");
        }
        return candidate;
    }

    private void pairDevice() {
        final String pin = pinInput.getText().toString().trim().toUpperCase();
        final String endpoint;
        try {
            endpoint = normalizeEndpoint();
        } catch (Exception error) {
            statusText.setText(error.getMessage() == null ? "Invalid desktop URL." : error.getMessage());
            return;
        }
        if (!pin.matches("[A-Z0-9]{6}")) {
            statusText.setText("Enter the six-character code shown in JARVIS → REMOTE CONTROL.");
            return;
        }

        pairButton.setEnabled(false);
        statusText.setText("Pairing securely…");
        pairingExecutor.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("pin", pin);
                RequestBody body = RequestBody.create(
                        MediaType.parse("application/json; charset=utf-8"), payload.toString());
                Request request = new Request.Builder()
                        .url(endpoint + "/api/native-pair")
                        .post(body)
                        .header("Cache-Control", "no-store")
                        .build();
                try (Response response = httpClient.newCall(request).execute()) {
                    String raw = response.body() == null ? "{}" : response.body().string();
                    JSONObject result = new JSONObject(raw);
                    if (!response.isSuccessful() || !result.optBoolean("ok")) {
                        String reason = result.optString("error", "Pairing failed. Check the code and try again.");
                        throw new IllegalStateException(reason);
                    }
                    String token = result.getString("device_token");
                    SecureTokenStore.saveDeviceToken(this, token);
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                            .putString(PREF_BASE_URL, endpoint).apply();
                    runOnUiThread(() -> {
                        baseUrl = endpoint;
                        deviceToken = token;
                        pinInput.setText("");
                        pairedText.setText("DEVICE PAIRED");
                        pairedText.setTextColor(Color.rgb(92, 242, 255));
                        statusText.setText("Pairing complete. Tap START VOICE when you want to use the tablet mic.");
                        pairButton.setEnabled(true);
                        updateButtons();
                        Toast.makeText(this, "JARVIS tablet paired.", Toast.LENGTH_SHORT).show();
                    });
                }
            } catch (Exception error) {
                String message = error.getMessage();
                runOnUiThread(() -> {
                    statusText.setText(message == null ? "Pairing failed. Check the private URL." : message);
                    pairButton.setEnabled(true);
                    updateButtons();
                });
            }
        });
    }

    private void toggleVoice() {
        if (voiceActive) {
            stopService(new Intent(this, AudioBridgeService.class));
            voiceActive = false;
            orbView.setActive(false);
            statusText.setText("Voice bridge stopped.");
            updateButtons();
            return;
        }
        if (deviceToken == null || deviceToken.isEmpty()) {
            statusText.setText("Pair this tablet with JARVIS first.");
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            pendingStart = true;
            requestAudioPermissions();
            return;
        }
        startVoiceBridge();
    }

    private void requestAudioPermissions() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(new String[]{
                    Manifest.permission.RECORD_AUDIO,
                    Manifest.permission.POST_NOTIFICATIONS
            }, REQUEST_PERMISSIONS);
        } else {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_PERMISSIONS);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_PERMISSIONS) return;
        boolean micGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
        pendingStart = false;
        if (micGranted) {
            startVoiceBridge();
        } else {
            statusText.setText("Microphone permission is required for tablet voice.");
        }
        if (Build.VERSION.SDK_INT >= 33
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "Allow notifications so Android can clearly show when the microphone service is active.", Toast.LENGTH_LONG).show();
        }
    }

    private void startVoiceBridge() {
        try {
            baseUrl = normalizeEndpoint();
        } catch (Exception error) {
            statusText.setText(error.getMessage() == null ? "Enter the paired desktop URL." : error.getMessage());
            return;
        }
        Intent intent = new Intent(this, AudioBridgeService.class);
        intent.setAction(AudioBridgeService.ACTION_START);
        intent.putExtra(AudioBridgeService.EXTRA_BASE_URL, baseUrl);
        intent.putExtra(AudioBridgeService.EXTRA_DEVICE_TOKEN, deviceToken);
        ContextCompat.startForegroundService(this, intent);
        voiceActive = true;
        orbView.setActive(false);
        statusText.setText("Connecting to your JARVIS desktop…");
        updateButtons();
    }

    private void updateButtons() {
        if (voiceButton != null) {
            voiceButton.setText(voiceActive ? "STOP VOICE" : "START VOICE");
            voiceButton.setEnabled(voiceActive || (deviceToken != null && !deviceToken.isEmpty()));
            voiceButton.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                    voiceActive ? Color.rgb(255, 104, 116) : Color.rgb(92, 242, 255)));
            voiceButton.setTextColor(voiceActive ? Color.WHITE : Color.rgb(3, 15, 25));
        }
        if (pairedText != null && deviceToken != null && !deviceToken.isEmpty()
                && !pairedText.getText().toString().contains("PAIRED")) {
            pairedText.setText("DEVICE PAIRED");
            pairedText.setTextColor(Color.rgb(92, 242, 255));
        }
    }

    @Override
    protected void onDestroy() {
        if (receiverRegistered) {
            try {
                unregisterReceiver(bridgeReceiver);
            } catch (Exception ignored) {
            }
        }
        pairingExecutor.shutdownNow();
        super.onDestroy();
    }
}
