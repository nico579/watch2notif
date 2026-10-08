package io.github.nico579.watch2notif;

import android.app.Application;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class PairingTest {
    private JSONObject vector() throws Exception {
        try (java.io.InputStream input = getClass().getResourceAsStream("/pairing_vector.json")) {
            assertNotNull(input); return new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    @Test public void decryptsPythonAesGcmAndImportsEverySourceAndCredential() throws Exception {
        JSONObject vector = vector(); PairingClient.Ticket ticket = PairingClient.parseTicket(vector.getJSONObject("qr").toString());
        PairingClient.Received received = PairingClient.decrypt(ticket, vector.getJSONObject("response"));
        assertEquals(5, received.feeds.size()); assertEquals("github-test-value", received.github);
        assertEquals("youtube-test-value", received.youtube); assertEquals("claude-test-value", received.claude);
        assertEquals("Seulement les questions.", received.feeds.get(0).filter); assertFalse(received.feeds.get(3).enabled);
        assertTrue(Arrays.equals(new byte[32], ticket.key));
    }

    @Test public void wrongKeyAndAlteredCiphertextAreRejected() throws Exception {
        JSONObject vector = vector(); PairingClient.Ticket ticket = PairingClient.parseTicket(vector.getJSONObject("qr").toString());
        ticket.key[0] ^= 1;
        try { PairingClient.decrypt(ticket, vector.getJSONObject("response")); fail(); } catch (SourceException expected) { assertEquals("pair_invalid", expected.code); }
        JSONObject response = vector.getJSONObject("response"); String encrypted = response.getString("ciphertext");
        response.put("ciphertext", (encrypted.charAt(0) == 'A' ? 'B' : 'A') + encrypted.substring(1));
        try { PairingClient.decrypt(PairingClient.parseTicket(vector.getJSONObject("qr").toString()), response); fail(); }
        catch (SourceException expected) { assertEquals("pair_invalid", expected.code); }
    }

    @Test public void qrCannotContactPublicHostsOrUnrelatedLocalServices() throws Exception {
        for (String url : new String[]{"http://8.8.8.8:54321/v1/config", "http://example.org:54321/v1/config", "file:///v1/config",
                "http://192.168.1.2:54321/admin", "http://192.168.1.2:54321/v1/config?token=x", "http://192.168.1.2:80/v1/config"}) {
            JSONObject qr = vector().getJSONObject("qr"); qr.put("url", url);
            try { PairingClient.parseTicket(qr.toString()); fail(url); } catch (SourceException expected) { assertEquals("pair_invalid", expected.code); }
        }
    }

    @Test public void privateAddressValidationDoesNotUseDnsOrAmbiguousOctal() {
        assertTrue(PairingClient.privateIPv4("10.0.0.1")); assertTrue(PairingClient.privateIPv4("172.31.1.1"));
        assertFalse(PairingClient.privateIPv4("172.32.1.1")); assertFalse(PairingClient.privateIPv4("127.0.0.1"));
        assertFalse(PairingClient.privateIPv4("192.168.001.1")); assertFalse(PairingClient.privateIPv4("192.168.1.300"));
    }
}
