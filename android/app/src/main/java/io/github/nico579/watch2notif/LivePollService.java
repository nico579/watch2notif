package io.github.nico579.watch2notif;

import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public final class LivePollService extends Service {
    static final String STOP = "stop";
    static volatile boolean running;
    private ScheduledExecutorService executor;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if ((intent != null && STOP.equals(intent.getAction())) || Store.get(this).paused()) { stopSelf(); return START_NOT_STICKY; }
        try {
            Notifications.channels(this);
            if (Build.VERSION.SDK_INT >= 29) startForeground(Notifications.SERVICE_ID, Notifications.monitoring(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(Notifications.SERVICE_ID, Notifications.monitoring(this));
            running = true;
            if (executor == null) {
                executor = Executors.newSingleThreadScheduledExecutor();
                executor.scheduleWithFixedDelay(() -> {
                    if (Store.get(this).paused()) { stopSelf(); return; }
                    new PollEngine(this).poll(false);
                }, 0, 5, TimeUnit.SECONDS);
            }
            WatchApp.updated(this);
        } catch (RuntimeException unavailable) { stopSelf(); }
        // A quick session is started only by a visible user action, never automatically at boot.
        return START_NOT_STICKY;
    }

    @Override public void onTimeout(int startId, int foregroundServiceType) { stopSelf(); }

    @Override public void onDestroy() {
        running = false;
        if (executor != null) executor.shutdownNow();
        stopForeground(STOP_FOREGROUND_REMOVE); WatchApp.updated(this); super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
