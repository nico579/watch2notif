package io.github.nico579.watch2notif;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

/** The visible report survives rotations and temporary backgrounding; no secrets are saved. */
final class SmokeSession {
    private final Handler main = new Handler(Looper.getMainLooper());
    final List<AccessSmokeTest.Row> rows;
    boolean running = true;
    private boolean closed;
    private Runnable listener;
    private final Thread worker;
    SmokeSession(Context context, List<Feed> feeds) {
        this(feeds, new AccessSmokeTest(context, new Network.HttpTransport(), new SecretStore(context)::get));
    }
    SmokeSession(List<Feed> feeds, AccessSmokeTest test) {
        rows = AccessSmokeTest.rows(feeds);
        worker = new Thread(() -> {
            try {
                test.run(feeds, row -> main.post(() -> { if (!closed) { rows.set(row.index, row); changed(); } }));
            } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            main.post(() -> { if (!closed) { running = false; changed(); } });
        }, "watch2notif-smoke");
        worker.setDaemon(true); worker.start();
    }
    void attach(Runnable activity) { listener = activity; changed(); }
    void detach() { listener = null; }
    private void changed() { if (listener != null) listener.run(); }
    void close() { closed = true; worker.interrupt(); detach(); }
}
