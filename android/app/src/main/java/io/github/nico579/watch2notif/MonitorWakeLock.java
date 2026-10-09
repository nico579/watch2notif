package io.github.nico579.watch2notif;

import android.content.Context;
import android.os.PowerManager;
import android.os.SystemClock;

/** Explicit fast mode keeps the CPU available between polls, without keeping the screen on. */
final class MonitorWakeLock implements AutoCloseable {
    static final long LEASE_MILLIS = 10 * 60 * 1000L;
    private final PowerManager.WakeLock lock;
    private long renewed;
    private boolean closed;

    MonitorWakeLock(Context context) {
        PowerManager power = context.getSystemService(PowerManager.class);
        if (power == null) throw new IllegalStateException("Power manager unavailable");
        lock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "watch2notif:fast-monitoring");
        lock.setReferenceCounted(false);
    }

    synchronized void renew() {
        if (closed) return;
        long now = SystemClock.elapsedRealtime();
        if (!lock.isHeld() || now - renewed >= 60000) {
            // A stalled loop cannot hold the CPU indefinitely. A normal pass is bounded to eight minutes.
            lock.acquire(LEASE_MILLIS); renewed = now;
        }
    }

    synchronized boolean held() { return lock.isHeld(); }

    @Override public synchronized void close() {
        closed = true;
        if (lock.isHeld()) lock.release();
    }
}
