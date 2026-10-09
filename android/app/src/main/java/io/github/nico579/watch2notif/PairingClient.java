package io.github.nico579.watch2notif;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.NetworkCapabilities;
import android.net.RouteInfo;
import android.util.Base64;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.ConnectException;
import java.net.InetAddress;
import java.net.Proxy;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import static io.github.nico579.watch2notif.Models.*;

final class PairingClient {
    private static final byte[] AAD = "watch2notif-transfer-v1".getBytes(StandardCharsets.UTF_8);
    interface ConnectionFactory { HttpURLConnection open(URL address, Proxy proxy) throws IOException; }
    static final class Ticket {
        final String url, code;
        final byte[] key;
        Ticket(String url, String code, byte[] key) { this.url = url; this.code = code; this.key = key; }
    }
    static final class Received {
        final List<Feed> feeds;
        final String github, youtube, claude;
        Received(List<Feed> feeds, String github, String youtube, String claude) {
            this.feeds = feeds; this.github = github; this.youtube = youtube; this.claude = claude;
        }
    }

    static Ticket parseTicket(String text) throws SourceException {
        try {
            if (text.length() > 2048) throw new SourceException("pair_invalid");
            JSONObject qr = new JSONObject(text);
            if (!"watch2notif-pair".equals(qr.optString("type")) || qr.getInt("version") != 1) throw new SourceException("pair_invalid");
            String address = qr.getString("url"), key = qr.getString("key"), code = qr.getString("code");
            URI uri = new URI(address);
            if (!"http".equals(uri.getScheme()) || uri.getRawUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                    || !"/v1/config".equals(uri.getPath()) || uri.getPort() < 1024 || uri.getPort() > 65535 || !privateIPv4(uri.getHost())
                    || !key.matches("[A-Za-z0-9_-]{43}") || !code.matches("[A-Za-z0-9_-]{43}")) throw new SourceException("pair_invalid");
            byte[] decodedKey = decode(key);
            if (decodedKey.length != 32) throw new SourceException("pair_invalid");
            return new Ticket(address, code, decodedKey);
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("pair_invalid"); }
    }

    static boolean privateIPv4(String host) {
        if (host == null || !host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}")) return false;
        String[] parts = host.split("\\."); int[] value = new int[4];
        for (int i = 0; i < 4; i++) {
            value[i] = Integer.parseInt(parts[i]);
            if (value[i] > 255 || !String.valueOf(value[i]).equals(parts[i])) return false;
        }
        return value[0] == 10 || value[0] == 172 && value[1] >= 16 && value[1] <= 31 || value[0] == 192 && value[1] == 168;
    }

    static byte[] decode(String value) { return Base64.decode(value, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING); }

    static Received decrypt(Ticket ticket, JSONObject response) throws SourceException {
        try {
            if (response.getInt("version") != 1) throw new SourceException("pair_invalid");
            byte[] nonce = decode(response.getString("nonce")), ciphertext = decode(response.getString("ciphertext"));
            if (nonce.length != 12 || ciphertext.length < 16 || ciphertext.length > 1024 * 1024) throw new SourceException("pair_invalid");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(ticket.key, "AES"), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(AAD);
            byte[] plaintext = cipher.doFinal(ciphertext);
            JSONObject config;
            try { config = new JSONObject(new String(plaintext, StandardCharsets.UTF_8)); }
            finally { Arrays.fill(plaintext, (byte)0); }
            List<Feed> feeds = Feed.importConfig(config);
            JSONObject credentials = config.optJSONObject("credentials");
            return new Received(feeds, credential(credentials, "github_token"), credential(credentials, "youtube_api_key"), credential(credentials, "anthropic_api_key"));
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("pair_invalid"); }
        finally { Arrays.fill(ticket.key, (byte)0); }
    }

    private static String credential(JSONObject values, String key) throws SourceException {
        String value = str(values, key, "").trim();
        if (value.length() > 4096 || value.contains("\r") || value.contains("\n")) throw new SourceException("pair_invalid");
        return value;
    }

    static android.net.Network localNetwork(ConnectivityManager manager, String host) throws IOException {
        if (manager == null) return null;
        // The validated QR host is a literal IPv4 address; this cannot resolve DNS.
        InetAddress destination = InetAddress.getByName(host);
        android.net.Network fallback = null;
        for (android.net.Network network : manager.getAllNetworks()) {
            NetworkCapabilities capabilities = manager.getNetworkCapabilities(network);
            if (capabilities == null || capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
                    || !(capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))) continue;
            if (fallback == null) fallback = network;
            LinkProperties properties = manager.getLinkProperties(network);
            if (properties != null) for (RouteInfo route : properties.getRoutes()) {
                if (!route.isDefaultRoute() && route.matches(destination)) return network;
            }
        }
        return fallback;
    }

    static Received receive(Context context, String qr) throws SourceException {
        return receive(qr, connections(context.getApplicationContext()));
    }

    static ConnectionFactory connections(Context context) {
        return (address, proxy) -> {
            ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            android.net.Network network = localNetwork(manager, address.getHost());
            // Bind this connection only; provider requests keep their normal network.
            return (HttpURLConnection) (network == null ? address.openConnection(proxy) : network.openConnection(address, proxy));
        };
    }

    static Received receive(String qr) throws SourceException {
        return receive(qr, (address, proxy) -> (HttpURLConnection) address.openConnection(proxy));
    }

    static Received receive(String qr, ConnectionFactory connections) throws SourceException {
        return receive(parseTicket(qr), connections);
    }

    static Received receive(Ticket ticket, ConnectionFactory connections) throws SourceException {
        HttpURLConnection connection = null;
        try {
            connection = connections.open(new URI(ticket.url).toURL(), Proxy.NO_PROXY);
            connection.setConnectTimeout(15000); connection.setReadTimeout(15000); connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            byte[] request = new JSONObject().put("code", ticket.code).toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(request.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(request); }
            int status = connection.getResponseCode();
            if (status == 403 || status == 410) throw new SourceException("pair_expired");
            if (status != 200) throw new SourceException("pair_http", status);
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096]; int count;
                while ((count = input.read(buffer)) != -1) {
                    if (output.size() + count > 2 * 1024 * 1024) throw new SourceException("pair_invalid");
                    output.write(buffer, 0, count);
                }
                JSONObject response;
                try { response = new JSONObject(output.toString(StandardCharsets.UTF_8.name())); }
                catch (Exception ignored) { throw new SourceException("pair_invalid"); }
                return decrypt(ticket, response);
            }
        } catch (SourceException failure) { throw failure; }
        catch (SocketTimeoutException ignored) { throw new SourceException("pair_timeout"); }
        catch (ConnectException ignored) { throw new SourceException("pair_refused"); }
        catch (Exception ignored) { throw new SourceException("pair_network"); }
        finally {
            Arrays.fill(ticket.key, (byte)0);
            if (connection != null) connection.disconnect();
        }
    }

    static String endpoint(String qr) {
        Ticket ticket = null;
        try {
            ticket = parseTicket(qr);
            URI address = URI.create(ticket.url);
            return address.getHost() + ":" + address.getPort();
        } catch (Exception ignored) { return ""; }
        finally { if (ticket != null) Arrays.fill(ticket.key, (byte)0); }
    }

    static int errorMessage(String code) {
        switch (code) {
            case "pair_invalid": return R.string.pair_invalid;
            case "pair_expired": return R.string.pair_expired;
            case "pair_timeout": return R.string.pair_timeout;
            case "pair_refused": return R.string.pair_refused;
            case "pair_http": return R.string.pair_http;
            default: return R.string.pair_network;
        }
    }
}
