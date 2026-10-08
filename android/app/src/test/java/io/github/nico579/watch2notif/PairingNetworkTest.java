package io.github.nico579.watch2notif;

import android.app.Application;
import android.content.Context;
import android.net.ConnectivityManager;
import android.net.IpPrefix;
import android.net.LinkProperties;
import android.net.NetworkCapabilities;
import android.net.RouteInfo;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowConnectivityManager;
import org.robolectric.shadows.ShadowNetwork;
import org.robolectric.util.ReflectionHelpers;
import org.robolectric.util.ReflectionHelpers.ClassParameter;
import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Proxy;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class PairingNetworkTest {
    private JSONObject vector() throws Exception {
        try (InputStream input = getClass().getResourceAsStream("/pairing_vector.json")) {
            assertNotNull(input); return new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    private static final class Connection extends HttpURLConnection {
        final ByteArrayOutputStream request = new ByteArrayOutputStream();
        final int status;
        final byte[] response;
        boolean disconnected;
        int responses, reads;
        Connection(URL address, int status, byte[] response) { super(address); this.status = status; this.response = response; }
        @Override public OutputStream getOutputStream() { return request; }
        @Override public int getResponseCode() { responses++; return status; }
        @Override public InputStream getInputStream() { reads++; return new ByteArrayInputStream(response); }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() { }
        int fixedLength() { return fixedContentLength; }
    }

    @Test public void encryptedConfigurationUsesOneDirectPostWithoutRedirectsOrSecretsInUrl() throws Exception {
        JSONObject vector = vector(); String qr = vector.getJSONObject("qr").toString();
        Connection connection = new Connection(new URL(vector.getJSONObject("qr").getString("url")), 200,
                vector.getJSONObject("response").toString().getBytes(StandardCharsets.UTF_8));
        AtomicInteger opens = new AtomicInteger();
        PairingClient.Received received = PairingClient.receive(qr, (url, proxy) -> {
            opens.incrementAndGet(); assertEquals(connection.getURL(), url); assertSame(Proxy.NO_PROXY, proxy); return connection;
        });
        assertEquals(1, opens.get()); assertEquals(1, connection.responses); assertEquals(1, connection.reads);
        assertEquals("POST", connection.getRequestMethod()); assertEquals("application/json", connection.getRequestProperty("Content-Type"));
        assertFalse(connection.getInstanceFollowRedirects()); assertFalse(connection.getUseCaches());
        assertEquals(15000, connection.getConnectTimeout()); assertEquals(15000, connection.getReadTimeout());
        assertEquals(connection.request.size(), connection.fixedLength());
        JSONObject body = new JSONObject(connection.request.toString(StandardCharsets.UTF_8.name()));
        assertEquals(1, body.length()); assertEquals(vector.getJSONObject("qr").getString("code"), body.getString("code"));
        assertNull(connection.getURL().getQuery()); assertTrue(connection.disconnected);
        assertEquals(5, received.feeds.size()); assertEquals("claude-test-value", received.claude);
    }

    @Test public void httpStatusesAreDistinctAndNeverTriggerRedirectsOrRetries() throws Exception {
        String qr = vector().getJSONObject("qr").toString();
        for (int status : new int[]{403, 410, 404, 407, 302, 500}) {
            Connection connection = new Connection(new URL("http://192.168.1.2:54321/v1/config"), status, new byte[0]);
            AtomicInteger opens = new AtomicInteger();
            try { PairingClient.receive(qr, (url, proxy) -> { opens.incrementAndGet(); return connection; }); fail(); }
            catch (SourceException expected) {
                assertEquals(status == 403 || status == 410 ? "pair_expired" : "pair_http", expected.code);
                if (expected.code.equals("pair_http")) assertEquals(status, expected.httpStatus);
            }
            assertEquals(1, opens.get()); assertEquals(0, connection.reads); assertTrue(connection.disconnected);
        }
    }

    @Test public void timeoutRefusalAndOtherNetworkErrorsAreSanitizedAndEraseTheKey() throws Exception {
        IOException[] failures = {new SocketTimeoutException("private details"), new ConnectException("private details"), new IOException("private details")};
        String[] expectedCodes = {"pair_timeout", "pair_refused", "pair_network"};
        for (int i = 0; i < failures.length; i++) {
            PairingClient.Ticket ticket = PairingClient.parseTicket(vector().getJSONObject("qr").toString());
            IOException failure = failures[i]; AtomicInteger opens = new AtomicInteger();
            try { PairingClient.receive(ticket, (url, proxy) -> { opens.incrementAndGet(); throw failure; }); fail(); }
            catch (SourceException expected) { assertEquals(expectedCodes[i], expected.getMessage()); }
            assertEquals(1, opens.get()); assertArrayEquals(new byte[32], ticket.key);
        }
    }

    @Test public void invalidResponseAndDiagnosticEndpointNeverExposeQrSecrets() throws Exception {
        JSONObject qr = vector().getJSONObject("qr");
        Connection connection = new Connection(new URL(qr.getString("url")), 200, "not json".getBytes(StandardCharsets.UTF_8));
        try { PairingClient.receive(qr.toString(), (url, proxy) -> connection); fail(); }
        catch (SourceException expected) { assertEquals("pair_invalid", expected.code); }
        assertTrue(connection.disconnected);
        String endpoint = PairingClient.endpoint(qr.toString());
        assertEquals("192.168.1.2:54321", endpoint); assertFalse(endpoint.contains(qr.getString("code"))); assertFalse(endpoint.contains(qr.getString("key")));
        assertEquals("", PairingClient.endpoint("not a QR"));
        assertEquals(R.string.pair_timeout, PairingClient.errorMessage("pair_timeout"));
        assertEquals(R.string.pair_refused, PairingClient.errorMessage("pair_refused"));
        assertEquals(R.string.pair_http, PairingClient.errorMessage("pair_http"));
    }

    @Test public void realHttpPostKeepsExpectedHostLengthAndDecryptsPythonFixture() throws Exception {
        JSONObject vector = vector(); JSONObject qr = vector.getJSONObject("qr");
        byte[] encrypted = vector.getJSONObject("response").toString().getBytes(StandardCharsets.UTF_8);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) {
            server.setSoTimeout(3000);
            Future<List<String>> observed = executor.submit(() -> {
                try (Socket socket = server.accept()) {
                    socket.setSoTimeout(3000);
                    BufferedReader input = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                    List<String> lines = new ArrayList<>(); lines.add(input.readLine()); String line; int length = 0;
                    while ((line = input.readLine()) != null && !line.isEmpty()) {
                        lines.add(line);
                        if (line.toLowerCase(java.util.Locale.ROOT).startsWith("content-length:")) length = Integer.parseInt(line.substring(line.indexOf(':') + 1).trim());
                    }
                    char[] body = new char[length]; int read = 0;
                    while (read < length) { int count = input.read(body, read, length - read); if (count < 0) throw new IOException("incomplete request"); read += count; }
                    lines.add(new String(body));
                    OutputStream output = socket.getOutputStream();
                    output.write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + encrypted.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                    output.write(encrypted); output.flush(); return lines;
                }
            });
            PairingClient.Received received = PairingClient.receive(qr.toString(), (url, proxy) -> {
                assertSame(Proxy.NO_PROXY, proxy);
                return (HttpURLConnection) new URL("http://127.0.0.1:" + server.getLocalPort() + url.getPath()).openConnection(proxy);
            });
            List<String> request = observed.get(3, TimeUnit.SECONDS);
            assertEquals("POST /v1/config HTTP/1.1", request.get(0));
            assertTrue(request.stream().anyMatch(header -> header.equalsIgnoreCase("Host: 127.0.0.1:" + server.getLocalPort())));
            JSONObject body = new JSONObject(request.get(request.size() - 1));
            assertEquals(qr.getString("code"), body.getString("code")); assertEquals(1, body.length());
            assertEquals(5, received.feeds.size()); assertEquals("github-test-value", received.github);
        } finally { executor.shutdownNow(); }
    }

    private android.net.Network addNetwork(ShadowConnectivityManager shadow, int id, int... transports) {
        android.net.Network network = ShadowNetwork.newInstance(id);
        NetworkCapabilities.Builder capabilities = new NetworkCapabilities.Builder();
        for (int transport : transports) capabilities.addTransportType(transport);
        shadow.addNetwork(network, null); shadow.setNetworkCapabilities(network, capabilities.build());
        return network;
    }

    @Test public void pairingPrefersMatchingPhysicalLanWithoutBindingTheProcess() throws Exception {
        ConnectivityManager manager = (ConnectivityManager) RuntimeEnvironment.getApplication().getSystemService(Context.CONNECTIVITY_SERVICE);
        ShadowConnectivityManager shadow = shadowOf(manager); shadow.clearAllNetworks();
        addNetwork(shadow, 1, NetworkCapabilities.TRANSPORT_CELLULAR);
        addNetwork(shadow, 2, NetworkCapabilities.TRANSPORT_WIFI, NetworkCapabilities.TRANSPORT_VPN);
        android.net.Network ethernet = addNetwork(shadow, 3, NetworkCapabilities.TRANSPORT_ETHERNET);
        android.net.Network wifi = addNetwork(shadow, 4, NetworkCapabilities.TRANSPORT_WIFI);
        RouteInfo route = ReflectionHelpers.callConstructor(RouteInfo.class,
                ClassParameter.from(IpPrefix.class, new IpPrefix(InetAddress.getByName("192.168.1.0"), 24)),
                ClassParameter.from(InetAddress.class, null), ClassParameter.from(String.class, null));
        LinkProperties link = new LinkProperties(); link.addRoute(route); shadow.setLinkProperties(wifi, link);
        assertEquals(wifi, PairingClient.localNetwork(manager, "192.168.1.13"));
        shadow.removeNetwork(wifi); assertEquals(ethernet, PairingClient.localNetwork(manager, "192.168.1.13"));
        shadow.removeNetwork(ethernet); assertNull(PairingClient.localNetwork(manager, "192.168.1.13"));
        assertNull(manager.getBoundNetworkForProcess());
    }
}
