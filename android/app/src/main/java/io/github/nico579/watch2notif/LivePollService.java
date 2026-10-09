package io.github.nico579.watch2notif;

import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class LivePollService extends Service {
    static final String STOP = "stop";
    static volatile boolean running;
    private ScheduledExecutorService executor;
    private MonitorWakeLock wake;
    private volatile boolean stopping;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        MonitoringState state = new MonitoringState(this);
        if (intent != null && STOP.equals(intent.getAction())) {
            state.stop(); finish(); return START_NOT_STICKY;
        }
        // A null intent is a system restart of an already requested sticky service.
        if (!state.requested() || !state.interruption().isEmpty() || !MonitoringState.eligible(this)) {
            if (!MonitoringState.eligible(this)) state.stop();
            finish(); return START_NOT_STICKY;
        }
        try {
            Notifications.channels(this);
            if (Build.VERSION.SDK_INT >= 29) startForeground(Notifications.SERVICE_ID, Notifications.monitoring(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(Notifications.SERVICE_ID, Notifications.monitoring(this));
            if (wake == null) wake = new MonitorWakeLock(this);
            wake.renew();
            running = true;
            Notifications.clearMonitoringInterruption(this);
            if (executor == null) startLoop();
            WatchApp.updated(this);
            return START_STICKY;
        } catch (RuntimeException unavailable) {
            state.interrupt(MonitoringState.UNAVAILABLE); finish();
            Notifications.monitoringInterrupted(this, R.string.live_unavailable);
            return START_NOT_STICKY;
        }
    }

    void startLoop() {
        executor = createExecutor();
        executor.scheduleWithFixedDelay(this::tick, 0, 5, TimeUnit.SECONDS);
    }

    ScheduledExecutorService createExecutor() { return Executors.newSingleThreadScheduledExecutor(); }

    PollEngine.Report checkSources() { return new PollEngine(this).poll(false); }

    void tick() {
        if (stopping) return;
        MonitoringState state = new MonitoringState(this);
        try {
            if (!state.requested() || !MonitoringState.eligible(this)) { state.stop(); finish(); return; }
            wake.renew();
            state.completed(checkSources(), System.currentTimeMillis());
        } catch (RuntimeException unavailable) {
            // ScheduledExecutor would otherwise silently cancel all future checks after an exception.
            state.interrupt(MonitoringState.UNAVAILABLE); finish();
            Notifications.monitoringInterrupted(this, R.string.live_unavailable);
        }
    }

    @Override public void onTimeout(int startId, int foregroundServiceType) {
        new MonitoringState(this).interrupt(MonitoringState.LIMIT);
        finish();
        Notifications.monitoringInterrupted(this, R.string.live_limit);
    }

    private void finish() {
        stopping = true; running = false;
        if (executor != null) executor.shutdownNow();
        if (wake != null) wake.close();
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); WatchApp.updated(this);
    }

    @Override public void onDestroy() {
        finish(); super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
