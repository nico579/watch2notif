package io.github.nico579.watch2notif;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.PowerManager;

/** Device-local monitoring intent and aggregate health; never exports source data or credentials. */
final class MonitoringState {
    static final String LIMIT = "limit", UNAVAILABLE = "unavailable";
    private final SharedPreferences preferences;

    MonitoringState(Context context) { preferences = context.getSharedPreferences("monitoring", Context.MODE_PRIVATE); }

    boolean requested() { return preferences.getBoolean("requested", false); }
    String interruption() { return preferences.getString("interruption", ""); }
    long lastCycle() { return preferences.getLong("last_cycle", 0); }
    long cycles() { return preferences.getLong("cycles", 0); }
    int succeeded() { return preferences.getInt("succeeded", 0); }
    int failed() { return preferences.getInt("failed", 0); }

    boolean request() { return preferences.edit().putBoolean("requested", true).putString("interruption", "").commit(); }
    void stop() { preferences.edit().putBoolean("requested", false).putString("interruption", "").commit(); }
    void interrupt(String reason) { preferences.edit().putString("interruption", reason).apply(); }

    synchronized void completed(PollEngine.Report report, long now) {
        if (report.busy || !requested()) return;
        // Persist checks and a one-minute heartbeat, rather than writing on every five-second idle tick.
        if (report.checked == 0 && now >= lastCycle() && now - lastCycle() < 60000) return;
        SharedPreferences.Editor edit = preferences.edit().putLong("last_cycle", now).putLong("cycles", cycles() + 1);
        if (report.checked > 0) edit.putInt("succeeded", report.succeeded).putInt("failed", report.failed);
        edit.apply();
    }

    static boolean eligible(Context context) {
        Store store = Store.get(context);
        return !store.paused() && store.feeds().stream().anyMatch(feed -> feed.enabled);
    }

    static boolean batteryUnrestricted(Context context) {
        PowerManager power = context.getSystemService(PowerManager.class);
        return power != null && power.isIgnoringBatteryOptimizations(context.getPackageName());
    }

    /** Called only by a visible activity; never starts dataSync from a worker or boot receiver. */
    static boolean start(Context context) {
        MonitoringState state = new MonitoringState(context);
        if (!eligible(context)) return false;
        if (!state.request()) { state.interrupt(UNAVAILABLE); return false; }
        try {
            context.startForegroundService(new Intent(context, LivePollService.class));
            return true;
        } catch (RuntimeException failure) {
            state.interrupt(UNAVAILABLE); WatchApp.updated(context); return false;
        }
    }

    static void resumeVisible(Context context) {
        MonitoringState state = new MonitoringState(context);
        if (state.requested() && state.interruption().isEmpty() && !LivePollService.running && eligible(context)) start(context);
    }
}
