package io.github.nico579.watch2notif;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.net.HttpURLConnection;
import java.net.URI;

/** In-memory reception retained across Activity recreation; never saved to a Bundle or file. */
final class PairingSession {
    enum State { RECEIVING, RECEIVED, FAILED, IMPORTED, CLOSED }
    private static final long DEADLINE_MILLIS = 30000;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable deadline = this::timeout;
    final String endpoint;
    private State state = State.RECEIVING;
    private PairingClient.Received received;
    private SourceException failure;
    private Runnable listener;
    private volatile boolean stopped;
    private volatile HttpURLConnection connection;
    private Thread worker;

    PairingSession(Context context, String qr) {
        this(qr, PairingClient.connections(context.getApplicationContext()));
    }

    PairingSession(String qr, PairingClient.ConnectionFactory connections) {
        PairingClient.Ticket ticket;
        try {
            ticket = PairingClient.parseTicket(qr);
        } catch (SourceException invalid) {
            endpoint = ""; failure = invalid; state = State.FAILED; return;
        }
        URI address = URI.create(ticket.url);
        endpoint = address.getHost() + ":" + address.getPort();
        // This work must start immediately, even when WatchApp.IO is polling slow providers.
        worker = new Thread(() -> receive(ticket, connections), "watch2notif-pairing");
        worker.setDaemon(true);
        main.postDelayed(deadline, DEADLINE_MILLIS);
        worker.start();
    }

    State state() { return state; }
    PairingClient.Received received() { return received; }
    SourceException failure() { return failure; }

    void attach(Runnable currentActivity) { listener = currentActivity; changed(); }
    void detach() { listener = null; }
    private void changed() { if (listener != null) listener.run(); }

    private void receive(PairingClient.Ticket ticket, PairingClient.ConnectionFactory connections) {
        PairingClient.Received result = null;
        SourceException error = null;
        try {
            result = PairingClient.receive(ticket, (address, proxy) -> {
                if (stopped) throw new java.io.IOException("Reception closed");
                HttpURLConnection opened = connections.open(address, proxy);
                connection = opened;
                if (stopped) { opened.disconnect(); throw new java.io.IOException("Reception closed"); }
                return opened;
            });
        } catch (SourceException failed) { error = failed; }
        finally { connection = null; }
        final PairingClient.Received completed = result;
        final SourceException failed = error;
        main.post(() -> {
            if (state != State.RECEIVING) return;
            main.removeCallbacks(deadline);
            worker = null;
            received = completed;
            failure = failed;
            state = failed == null ? State.RECEIVED : State.FAILED;
            changed();
        });
    }

    private void timeout() {
        if (state != State.RECEIVING) return;
        stopTransport();
        failure = new SourceException("pair_timeout");
        state = State.FAILED;
        changed();
    }

    void imported() {
        if (state != State.RECEIVED) return;
        received = null;
        state = State.IMPORTED;
        changed();
    }

    void close() {
        main.removeCallbacks(deadline);
        detach();
        stopTransport();
        received = null;
        failure = null;
        state = State.CLOSED;
    }

    private void stopTransport() {
        stopped = true;
        if (worker != null) worker.interrupt();
        HttpURLConnection opened = connection;
        if (opened != null) {
            // Some implementations block in disconnect(); keep the UI responsive.
            Thread cancel = new Thread(opened::disconnect, "watch2notif-pair-cancel");
            cancel.setDaemon(true); cancel.start();
        }
    }
}
