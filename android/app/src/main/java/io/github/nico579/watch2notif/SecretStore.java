package io.github.nico579.watch2notif;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;

/** Credentials never enter the portable configuration, logs, notification text or provider errors. */
final class SecretStore {
    private static final String ALIAS = "watch2notif-api-credentials";
    private final Context context;
    SecretStore(Context context) { this.context = context.getApplicationContext(); }

    private SecretKey key() throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore"); keys.load(null);
        if (keys.containsAlias(ALIAS)) return (SecretKey) keys.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }

    synchronized String get(String name) throws Exception {
        String stored = Store.get(context).credentials().optString(name, "");
        if (stored.isEmpty()) return "";
        byte[] data = Base64.decode(stored, Base64.NO_WRAP);
        ByteBuffer buffer = ByteBuffer.wrap(data);
        int length = buffer.get() & 255;
        if (length != 12 || buffer.remaining() < length + 16) throw new IllegalStateException("Invalid encrypted credential");
        byte[] iv = new byte[length]; buffer.get(iv);
        byte[] encrypted = new byte[buffer.remaining()]; buffer.get(encrypted);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
        cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));
        return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
    }

    private String encode(String name, String value) throws Exception {
        if (value.trim().isEmpty()) return "";
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));
        byte[] encrypted = cipher.doFinal(value.trim().getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        return Base64.encodeToString(ByteBuffer.allocate(1 + iv.length + encrypted.length)
                .put((byte)iv.length).put(iv).put(encrypted).array(), Base64.NO_WRAP);
    }

    synchronized void save(String github, String youtube, String claude) throws Exception {
        Store.get(context).credentials(encrypted(github, youtube, claude));
    }

    synchronized JSONObject encrypted(String github, String youtube, String claude) throws Exception {
        String encryptedGithub = encode("github", github), encryptedYoutube = encode("youtube", youtube), encryptedClaude = encode("claude", claude);
        return new JSONObject().put("github", encryptedGithub).put("youtube", encryptedYoutube).put("claude", encryptedClaude);
    }
}
