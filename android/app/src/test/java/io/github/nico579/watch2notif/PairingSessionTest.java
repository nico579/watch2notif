package io.github.nico579.watch2notif;

import android.app.AlertDialog;
import android.app.Application;
import android.os.Bundle;
import android.os.Looper;
import android.widget.TextView;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowAlertDialog;
import org.robolectric.util.ReflectionHelpers;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class PairingSessionTest {
    private JSONObject vector;

    @Before public void reset() throws Exception {
        ReflectionHelpers.setStaticField(Store.class, "instance", null);
        File saved = new File(RuntimeEnvironment.getApplication().getFilesDir(), "watch2notif.json");
        if (saved.exists()) assertTrue(saved.delete());
        Notifications.channels(RuntimeEnvironment.getApplication());
        try (InputStream input = getClass().getResourceAsStream("/pairing_vector.json")) {
            assertNotNull(input); vector = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    private final class Connection extends HttpURLConnection {
        final CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        final boolean blocked;
        volatile boolean disconnected;
        Connection(boolean blocked) throws Exception { super(new URL(vector.getJSONObject("qr").getString("url"))); this.blocked = blocked; }
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public int getResponseCode() throws IOException {
            entered.countDown();
            if (blocked) try {
                if (!release.await(15, TimeUnit.SECONDS)) throw new IOException("Test deadline");
            } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); throw new IOException("Stopped"); }
            return 200;
        }
        @Override public InputStream getInputStream() throws IOException {
            try { return new ByteArrayInputStream(vector.getJSONObject("response").toString().getBytes(StandardCharsets.UTF_8)); }
            catch (Exception invalid) { throw new IOException("Fixture invalid"); }
        }
        @Override public void disconnect() { disconnected = true; release.countDown(); }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() { }
    }

    private PairingSession session(Connection connection) throws Exception {
        return new PairingSession(vector.getJSONObject("qr").toString(), (address, proxy) -> connection);
    }

    private void complete(PairingSession session) throws Exception {
        Thread worker = ReflectionHelpers.getField(session, "worker");
        if (worker != null) { worker.join(3000); assertFalse("Reception must finish promptly", worker.isAlive()); }
        shadowOf(Looper.getMainLooper()).idle();
    }

    private void display(MainActivity activity, PairingSession session) {
        ReflectionHelpers.setField(activity, "pairing", session);
        session.attach(() -> ReflectionHelpers.callInstanceMethod(activity, "showPairing"));
    }

    @Test public void receptionStartsWhileTheProviderQueueIsBusyAndDoesNotImportBeforeConfirmation() throws Exception {
        CountDownLatch polling = new CountDownLatch(1), releasePoll = new CountDownLatch(1);
        Future<?> poll = WatchApp.IO.submit(() -> {
            polling.countDown();
            try { releasePoll.await(15, TimeUnit.SECONDS); }
            catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
        });
        assertTrue(polling.await(3, TimeUnit.SECONDS));
        PairingSession session = session(new Connection(false));
        try {
            complete(session);
            assertEquals(PairingSession.State.RECEIVED, session.state());
            assertEquals(5, session.received().feeds.size());
            assertFalse("Provider work should still be blocked", poll.isDone());
            assertTrue(Store.get(RuntimeEnvironment.getApplication()).feeds().isEmpty());
        } finally { session.close(); releasePoll.countDown(); poll.cancel(true); }
    }

    @Test public void rotationRetainsProgressAndShowsTheResultOnTheNewActivityWithoutSavingSecrets() throws Exception {
        Connection connection = new Connection(true);
        PairingSession session = session(connection);
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            display(controller.get(), session);
            assertTrue(connection.entered.await(3, TimeUnit.SECONDS));
            AlertDialog progress = ShadowAlertDialog.getLatestAlertDialog(); assertTrue(progress.isShowing());
            Bundle saved = new Bundle(); controller.saveInstanceState(saved);
            for (String secret : new String[]{vector.getJSONObject("qr").getString("key"), vector.getJSONObject("qr").getString("code"),
                    "github-test-value", "youtube-test-value", "claude-test-value"}) assertFalse(saved.toString().contains(secret));
            MainActivity old = controller.get(); controller.recreate();
            assertNotSame(old, controller.get());
            assertSame(session, ReflectionHelpers.getField(controller.get(), "pairing"));
            assertFalse(progress.isShowing());
            assertTrue(ShadowAlertDialog.getLatestAlertDialog().isShowing());
            connection.release.countDown(); complete(session);
            AlertDialog result = ShadowAlertDialog.getLatestAlertDialog(); assertTrue(result.isShowing());
            TextView message = result.findViewById(android.R.id.message);
            assertEquals(controller.get().getString(R.string.pair_import_question, 5, 3), message.getText().toString());
            assertTrue(Store.get(controller.get()).feeds().isEmpty());
            result.getButton(AlertDialog.BUTTON_NEGATIVE).performClick();
            shadowOf(Looper.getMainLooper()).idle();
            assertEquals(PairingSession.State.CLOSED, session.state()); assertNull(session.received());
        } finally { session.close(); connection.release.countDown(); }
    }

    @Test public void anErrorCompletedWhilePausedIsDisplayedWhenTheActivityResumes() throws Exception {
        CountDownLatch opened = new CountDownLatch(1), release = new CountDownLatch(1);
        PairingSession session = new PairingSession(vector.getJSONObject("qr").toString(), (address, proxy) -> {
            opened.countDown();
            try { release.await(15, TimeUnit.SECONDS); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            throw new ConnectException("Private exception details");
        });
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            display(controller.get(), session); assertTrue(opened.await(3, TimeUnit.SECONDS));
            controller.pause(); release.countDown(); complete(session);
            assertEquals(PairingSession.State.FAILED, session.state());
            controller.resume();
            AlertDialog error = ShadowAlertDialog.getLatestAlertDialog(); assertTrue(error.isShowing());
            String message = ((TextView)error.findViewById(android.R.id.message)).getText().toString();
            assertTrue(message.startsWith(controller.get().getString(R.string.pair_refused)));
            assertFalse(message.contains("Private exception details"));
        } finally { release.countDown(); session.close(); }
    }

    @Test public void theOverallDeadlineShowsAnErrorAndPreventsALateSuccess() throws Exception {
        Connection connection = new Connection(true); PairingSession session = session(connection);
        try {
            assertTrue(connection.entered.await(3, TimeUnit.SECONDS));
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(31));
            assertEquals(PairingSession.State.FAILED, session.state());
            assertEquals("pair_timeout", session.failure().code);
            connection.release.countDown(); complete(session);
            assertEquals(PairingSession.State.FAILED, session.state()); assertNull(session.received());
        } finally { session.close(); connection.release.countDown(); }
    }

    @Test public void cancellingBeforeTheCompletionCallbackDiscardsDecryptedCredentials() throws Exception {
        PairingSession session = session(new Connection(false));
        Thread worker = ReflectionHelpers.getField(session, "worker");
        worker.join(3000); assertFalse(worker.isAlive());
        session.close(); shadowOf(Looper.getMainLooper()).idle();
        assertEquals(PairingSession.State.CLOSED, session.state()); assertNull(session.received());
        assertTrue(Store.get(RuntimeEnvironment.getApplication()).feeds().isEmpty());
    }

    @Test public void malformedQrProducesAVisibleTerminalStateWithoutOpeningANetwork() {
        PairingSession session = new PairingSession("not a QR", (address, proxy) -> { fail("Invalid QR must not open a connection"); return null; });
        assertEquals(PairingSession.State.FAILED, session.state()); assertEquals("pair_invalid", session.failure().code);
        assertEquals("", session.endpoint); session.close();
    }
}
