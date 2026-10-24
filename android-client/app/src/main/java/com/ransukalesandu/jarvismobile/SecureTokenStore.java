package com.ransukalesandu.jarvismobile;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

/** Stores the long-lived device token encrypted with a key held by Android Keystore. */
final class SecureTokenStore {
    private static final String FILE = "jarvis_secure_pairing";
    private static final String DEVICE_TOKEN = "device_token";

    private SecureTokenStore() {}

    private static SharedPreferences open(Context context) throws Exception {
        MasterKey masterKey = new MasterKey.Builder(context.getApplicationContext())
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build();
        return EncryptedSharedPreferences.create(
                context.getApplicationContext(),
                FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        );
    }

    static String getDeviceToken(Context context) throws Exception {
        return open(context).getString(DEVICE_TOKEN, "");
    }

    static void saveDeviceToken(Context context, String token) throws Exception {
        if (token == null || token.isEmpty()) {
            throw new IllegalArgumentException("The device token must not be empty.");
        }
        open(context).edit().putString(DEVICE_TOKEN, token).apply();
    }

    static void clearDeviceToken(Context context) throws Exception {
        open(context).edit().remove(DEVICE_TOKEN).apply();
    }
}
