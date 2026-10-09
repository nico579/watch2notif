package io.github.nico579.watch2notif;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.util.function.Consumer;

/** Retained update operations use their own thread, independent of source polling. */
final class UpdateSession {
    enum State { IDLE, CHECKING, CURRENT, AVAILABLE, DOWNLOADING, VERIFYING, READY, FAILED }
    interface Factory { ReleaseUpdates create(); }
    interface Verifier { void verify(ReleaseUpdates.Downloaded apk, ReleaseUpdates.Release release) throws Exception; }
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Factory factory;
    private final Verifier verifier;
    private Runnable listener;
    private volatile ReleaseUpdates http;
    private Thread worker;
    private int generation;
    private long checkedAt;
    State state = State.IDLE;
    ReleaseUpdates.Release release;
    ReleaseUpdates.Downloaded downloaded;
    int failure = R.string.update_network, feedback, percent;

    UpdateSession(Context context) { this(context, ReleaseUpdates::new, (apk, release) -> ReleaseUpdates.verify(context.getApplicationContext(), apk, release)); }
    UpdateSession(Context context, Factory factory, Verifier verifier) { this.context = context.getApplicationContext(); this.factory = factory; this.verifier = verifier; }
    void attach(Runnable activity) { listener = activity; changed(); }
    void detach() { listener = null; }
    private void changed() { if (listener != null) listener.run(); }
    boolean busy() { return state == State.CHECKING || state == State.DOWNLOADING || state == State.VERIFYING; }
    void check(boolean force) {
        if (busy() || state == State.READY || (!force && checkedAt != 0 && System.currentTimeMillis() - checkedAt < 21600000L)) return;
        checkedAt = System.currentTimeMillis(); feedback = 0; state = State.CHECKING; changed();
        int expected = ++generation;
        ReleaseUpdates client = factory.create(); http = client;
        launch(() -> {
            try {
                ReleaseUpdates.Release found = client.check(BuildConfig.VERSION_NAME);
                main.post(() -> { if (generation != expected) return; release = found; state = found == null ? State.CURRENT : State.AVAILABLE; changed(); });
            } catch (Exception error) { failed(expected, error); }
        });
    }
    void download() {
        if (release == null || busy()) return;
        state = State.DOWNLOADING; percent = 0; feedback = 0; changed();
        int expected = ++generation;
        ReleaseUpdates.Release selected = release;
        ReleaseUpdates client = factory.create(); http = client;
        launch(() -> {
            ReleaseUpdates.Downloaded file = null;
            try {
                file = client.download(selected, new File(context.getCacheDir(), "updates"), (done, total) -> {
                    int value = (int)(done * 100 / total);
                    main.post(() -> { if (generation != expected || percent == value) return; percent = value; changed(); });
                });
                verifier.verify(file, selected);
                ReleaseUpdates.Downloaded verified = file;
                main.post(() -> { if (generation != expected) return; downloaded = verified; state = State.READY; changed(); });
            } catch (Exception error) {
                if (file != null) file.file.delete();
                failed(expected, error);
            }
        });
    }
    void prepareInstall(Consumer<File> install) {
        if (state != State.READY || downloaded == null) return;
        ReleaseUpdates.Downloaded selected = downloaded;
        ReleaseUpdates.Release version = release;
        int expected = ++generation;
        state = State.VERIFYING; feedback = 0; changed();
        launch(() -> {
            try {
                verifier.verify(selected, version);
                main.post(() -> { if (generation != expected) return; state = State.READY; changed(); install.accept(selected.file); });
            } catch (Exception error) { selected.file.delete(); failed(expected, error); }
        });
    }
    void feedback(int message) { feedback = message; changed(); }
    private void failed(int expected, Exception error) {
        int message = error instanceof ReleaseUpdates.Failure ? ((ReleaseUpdates.Failure)error).message : R.string.update_network;
        main.post(() -> { if (generation != expected) return; failure = message; state = State.FAILED; changed(); });
    }
    private void launch(Runnable task) { worker = new Thread(task, "watch2notif-update"); worker.setDaemon(true); worker.start(); }
    void cancel() {
        generation++;
        if (worker != null) worker.interrupt();
        ReleaseUpdates client = http;
        if (client != null) { Thread cancellation = new Thread(client::cancel, "watch2notif-update-cancel"); cancellation.setDaemon(true); cancellation.start(); }
        state = downloaded != null ? State.READY : release != null ? State.AVAILABLE : State.IDLE;
        changed();
    }
    void close() { detach(); cancel(); }
}
