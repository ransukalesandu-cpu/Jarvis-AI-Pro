package com.ransukalesandu.jarvismobile;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
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
    private static final String PREFS = "jarvis_mobile_settings";
    private static final String PREF_BASE_URL = "base_url";
    private static final int MAX_FEED_LINES = 100;

    private final ExecutorService pairingExecutor = Executors.newSingleThreadExecutor();
    private final OkHttpClient httpClient = new OkHttpClient.Builder().build();
    private final RemoteControlClient remoteClient = new RemoteControlClient();
    private final StringBuilder feedBuffer = new StringBuilder();

    private EditText endpointInput;
    private EditText pinInput;
    private EditText commandInput;
    private TextView statusText;
    private TextView pairedText;
    private TextView feedText;
    private Button pairButton;
    private Button connectButton;
    private Button sendButton;
    private HudOrbView orbView;

    private String baseUrl = "";
    private String deviceToken = "";
    private boolean connected = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.rgb(6, 10, 18));
        getWindow().setNavigationBarColor(Color.rgb(6, 10, 18));
        buildUi();
        loadSavedPairing();
        updateButtons();
    }

    private void buildUi() {
        ScrollView outer = new ScrollView(this);
        outer.setFillViewport(true);
        outer.setBackgroundColor(Color.rgb(6, 10, 18));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(24), dp(20), dp(24), dp(26));

        TextView brand = new TextView(this);
        brand.setText("J.A.R.V.I.S");
        brand.setTextColor(Color.rgb(92, 242, 255));
        brand.setTextSize(30);
        brand.setLetterSpacing(0.18f);
        brand.setGravity(Gravity.CENTER);
        brand.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.BOLD));
        root.addView(brand, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("REMOTE HUD  /  DESKTOP AUDIO MODE");
        subtitle.setTextColor(Color.rgb(121, 153, 177));
        subtitle.setTextSize(11);
        subtitle.setLetterSpacing(0.10f);
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subParams = matchWrap();
        subParams.topMargin = dp(5);
        root.addView(subtitle, subParams);

        orbView = new HudOrbView(this);
        LinearLayout.LayoutParams orbParams = new LinearLayout.LayoutParams(dp(220), dp(220));
        orbParams.gravity = Gravity.CENTER_HORIZONTAL;
        orbParams.topMargin = dp(2);
        orbParams.bottomMargin = dp(0);
        root.addView(orbView, orbParams);

        statusText = new TextView(this);
        statusText.setText("Pair with JARVIS on your PC. The PC microphone and external speaker stay in use.");
        statusText.setTextColor(Color.rgb(210, 224, 237));
        statusText.setTextSize(14);
        statusText.setGravity(Gravity.CENTER);
        statusText.setMinHeight(dp(48));
        root.addView(statusText, matchWrap());

        pairedText = new TextView(this);
        pairedText.setText("NOT PAIRED");
        pairedText.setTextColor(Color.rgb(255, 193, 105));
        pairedText.setTextSize(11);
        pairedText.setLetterSpacing(0.12f);
        pairedText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams pairedParams = matchWrap();
        pairedParams.topMargin = dp(2);
        pairedParams.bottomMargin = dp(16);
        root.addView(pairedText, pairedParams);

        root.addView(fieldLabel("PRIVATE DESKTOP URL"), matchWrap());
        endpointInput = new EditText(this);
        endpointInput.setSingleLine(true);
        endpointInput.setTextSize(14);
        endpointInput.setHint("https://your-pc.your-tailnet.ts.net");
        endpointInput.setHintTextColor(Color.rgb(95, 115, 135));
        endpointInput.setTextColor(Color.WHITE);
        endpointInput.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        styleInput(endpointInput);
        LinearLayout.LayoutParams endpointParams = matchWrap();
        endpointParams.topMargin = dp(6);
        endpointParams.bottomMargin = dp(12);
        root.addView(endpointInput, endpointParams);

        root.addView(fieldLabel("ONE-TIME PAIRING CODE"), matchWrap());
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
        pinInput.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        styleInput(pinInput);
        LinearLayout.LayoutParams pinParams = matchWrap();
        pinParams.topMargin = dp(6);
        pinParams.bottomMargin = dp(12);
        root.addView(pinInput, pinParams);

        pairButton = makeButton("PAIR TABLET", false);
        root.addView(pairButton, fullWidthButton());
        pairButton.setOnClickListener(v -> pairDevice());

        connectButton = makeButton("CONNECT REMOTE HUD", true);
        LinearLayout.LayoutParams connectParams = fullWidthButton();
        connectParams.topMargin = dp(10);
        root.addView(connectButton, connectParams);
        connectButton.setOnClickListener(v -> toggleConnection());

        TextView commandLabel = fieldLabel("SEND A COMMAND TO JARVIS");
        LinearLayout.LayoutParams labelParams = matchWrap();
        labelParams.topMargin = dp(22);
        root.addView(commandLabel, labelParams);

        LinearLayout commandRow = new LinearLayout(this);
        commandRow.setOrientation(LinearLayout.HORIZONTAL);
        commandRow.setGravity(Gravity.CENTER_VERTICAL);
        commandInput = new EditText(this);
        commandInput.setSingleLine(true);
        commandInput.setTextSize(14);
        commandInput.setHint("Type a command…");
        commandInput.setHintTextColor(Color.rgb(95, 115, 135));
        commandInput.setTextColor(Color.WHITE);
        commandInput.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEND);
        styleInput(commandInput);
        LinearLayout.LayoutParams commandParams = new LinearLayout.LayoutParams(0, dp(52), 1f);
        commandParams.rightMargin = dp(8);
        commandRow.addView(commandInput, commandParams);

        sendButton = makeButton("SEND", true);
        LinearLayout.LayoutParams sendParams = new LinearLayout.LayoutParams(dp(88), dp(52));
        commandRow.addView(sendButton, sendParams);
        sendButton.setOnClickListener(v -> sendCommand());
        commandInput.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) {
                sendCommand();
                return true;
            }
            return false;
        });
        root.addView(commandRow, matchWrap());

        TextView feedLabel = fieldLabel("LIVE DESKTOP STATUS");
        LinearLayout.LayoutParams feedLabelParams = matchWrap();
        feedLabelParams.topMargin = dp(22);
        root.addView(feedLabel, feedLabelParams);

        ScrollView feedScroll = new ScrollView(this);
        feedScroll.setBackgroundColor(Color.rgb(9, 18, 29));
        feedText = new TextView(this);
        feedText.setText("Waiting for desktop connection…\n");
        feedText.setTextColor(Color.rgb(180, 207, 221));
        feedText.setTextSize(12);
        feedText.setPadding(dp(12), dp(12), dp(12), dp(12));
        feedText.setTextIsSelectable(true);
        feedScroll.addView(feedText);
        LinearLayout.LayoutParams feedParams = matchWrap();
        feedParams.topMargin = dp(8);
        feedParams.height = dp(180);
        root.addView(feedScroll, feedParams);

        TextView note = new TextView(this);
        note.setText("MIC + SPEAKER: PC\nThis tablet is a remote display/controller only. JARVIS listens through the PC mic and speaks through the PC's selected speaker.");
        note.setTextColor(Color.rgb(105, 149, 166));
        note.setTextSize(11);
        note.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams noteParams = matchWrap();
        noteParams.topMargin = dp(16);
        root.addView(note, noteParams);

        outer.addView(root);
        setContentView(outer);
    }

    private void styleInput(EditText input) {
        input.setPadding(dp(14), dp(10), dp(14), dp(10));
        input.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(48, 90, 112)));
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
        button.setTextSize(12);
        button.setLetterSpacing(0.05f);
        button.setTextColor(primary ? Color.rgb(3, 15, 25) : Color.rgb(92, 242, 255));
        button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                primary ? Color.rgb(92, 242, 255) : Color.rgb(15, 35, 50)));
        return button;
    }

    private LinearLayout.LayoutParams fullWidthButton() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(50));
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
            statusText.setText("Secure token storage is unavailable. Pair this tablet again.");
        }
        if (!deviceToken.isEmpty()) {
            pairedText.setText("DEVICE PAIRED");
            pairedText.setTextColor(Color.rgb(92, 242, 255));
            statusText.setText("Paired. Connect to see desktop status or send a command.");
        }
    }

    private String normalizeEndpoint() throws Exception {
        String candidate = endpointInput.getText().toString().trim();
        while (candidate.endsWith("/")) candidate = candidate.substring(0, candidate.length() - 1);
        URL url = new URL(candidate);
        if (!"https".equalsIgnoreCase(url.getProtocol())) {
            throw new IllegalArgumentException("Use the private HTTPS URL from Tailscale Serve.");
        }
        if (url.getHost() == null || url.getHost().isEmpty()
                || (url.getPath() != null && !url.getPath().isEmpty() && !"/".equals(url.getPath()))
                || url.getQuery() != null || url.getRef() != null || url.getUserInfo() != null) {
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
                        throw new IllegalStateException(result.optString("error",
                                "Pairing failed. Check the code and try again."));
                    }
                    String token = result.getString("device_token");
                    SecureTokenStore.saveDeviceToken(this, token);
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(PREF_BASE_URL, endpoint).apply();
                    runOnUiThread(() -> {
                        baseUrl = endpoint;
                        deviceToken = token;
                        pinInput.setText("");
                        pairedText.setText("DEVICE PAIRED");
                        pairedText.setTextColor(Color.rgb(92, 242, 255));
                        statusText.setText("Paired. Tap CONNECT REMOTE HUD.");
                        appendFeed("SYSTEM", "Tablet paired with desktop JARVIS.");
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

    private void toggleConnection() {
        if (connected) {
            remoteClient.disconnect();
            connected = false;
            orbView.setActive(false);
            statusText.setText("Remote HUD disconnected. PC audio remains unchanged.");
            appendFeed("SYSTEM", "Remote HUD disconnected.");
            updateButtons();
            return;
        }
        if (deviceToken == null || deviceToken.isEmpty()) {
            statusText.setText("Pair this tablet with JARVIS first.");
            return;
        }
        try {
            baseUrl = normalizeEndpoint();
        } catch (Exception error) {
            statusText.setText(error.getMessage() == null ? "Enter the paired desktop URL." : error.getMessage());
            return;
        }

        connectButton.setEnabled(false);
        statusText.setText("Connecting to desktop JARVIS…");
        remoteClient.connect(baseUrl, deviceToken, new RemoteControlClient.Listener() {
            @Override
            public void onConnected() {
                runOnUiThread(() -> {
                    connected = true;
                    orbView.setActive(true);
                    statusText.setText("Connected. PC microphone and speaker remain active on the desktop.");
                    appendFeed("SYSTEM", "Remote HUD connected.");
                    updateButtons();
                });
            }

            @Override
            public void onDisconnected(String reason) {
                runOnUiThread(() -> {
                    connected = false;
                    orbView.setActive(false);
                    statusText.setText(reason + " Desktop audio remains on the PC.");
                    updateButtons();
                });
            }

            @Override
            public void onEvent(JSONObject event) {
                runOnUiThread(() -> handleEvent(event));
            }

            @Override
            public void onError(String message) {
                runOnUiThread(() -> {
                    statusText.setText(message);
                    appendFeed("ERROR", message);
                    updateButtons();
                });
            }
        });
    }

    private void handleEvent(JSONObject event) {
        String type = event.optString("type", "");
        if ("log".equals(type)) {
            appendFeed(event.optString("speaker", "JARVIS"), event.optString("text", ""));
        } else if ("status".equals(type)) {
            String state = event.optString("state", "unknown");
            statusText.setText("Desktop status: " + state + ". PC mic/speaker are in use by JARVIS.");
            appendFeed("STATUS", state);
        } else if ("sys".equals(type)) {
            appendFeed("SYSTEM", event.optString("text", ""));
        } else if ("wake".equals(type)) {
            appendFeed("WAKE", "JARVIS wake word detected.");
        } else if ("file_received".equals(type)) {
            appendFeed("FILE", "File received: " + event.optString("name", "file"));
        }
    }

    private void sendCommand() {
        String command = commandInput.getText().toString().trim();
        if (command.isEmpty()) return;
        if (!connected) {
            statusText.setText("Connect the remote HUD before sending commands.");
            return;
        }
        if (remoteClient.sendCommand(command)) {
            appendFeed("YOU", command);
            commandInput.setText("");
        } else {
            statusText.setText("Command could not be sent. Check the desktop connection.");
        }
    }

    private void appendFeed(String speaker, String message) {
        String clean = message == null ? "" : message.replaceAll("[\\r\\n]+", " ").trim();
        if (clean.isEmpty()) return;
        feedBuffer.append("[").append(speaker).append("] ").append(clean).append('\n');
        int newlineCount = 0;
        for (int i = 0; i < feedBuffer.length(); i++) {
            if (feedBuffer.charAt(i) == '\n') newlineCount++;
        }
        while (newlineCount > MAX_FEED_LINES) {
            int first = feedBuffer.indexOf("\n");
            if (first < 0) break;
            feedBuffer.delete(0, first + 1);
            newlineCount--;
        }
        feedText.setText(feedBuffer.toString());
    }

    private void updateButtons() {
        if (connectButton != null) {
            connectButton.setText(connected ? "DISCONNECT REMOTE HUD" : "CONNECT REMOTE HUD");
            connectButton.setEnabled(connected || (deviceToken != null && !deviceToken.isEmpty()));
            connectButton.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                    connected ? Color.rgb(255, 104, 116) : Color.rgb(92, 242, 255)));
            connectButton.setTextColor(connected ? Color.WHITE : Color.rgb(3, 15, 25));
        }
        if (sendButton != null) sendButton.setEnabled(connected);
        if (pairButton != null) pairButton.setEnabled(!connected);
    }

    @Override
    protected void onDestroy() {
        remoteClient.shutdown();
        pairingExecutor.shutdownNow();
        httpClient.dispatcher().cancelAll();
        httpClient.connectionPool().evictAll();
        super.onDestroy();
    }
}
