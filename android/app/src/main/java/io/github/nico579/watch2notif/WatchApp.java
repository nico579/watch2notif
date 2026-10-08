package io.github.nico579.watch2notif;

import android.app.Application;
import android.content.Context;
import android.content.Intent;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class WatchApp extends Application {
    static final String UPDATED = "io.github.nico579.watch2notif.UPDATED";
    static final ExecutorService IO = Executors.newSingleThreadExecutor();
    @Override public void onCreate() {
        super.onCreate();
        try { Notifications.channels(this); Scheduler.sync(this); }
        catch (RuntimeException unreadableData) { /* MainActivity displays the storage error; preserve the file. */ }
    }
    static void updated(Context context) { context.sendBroadcast(new Intent(UPDATED).setPackage(context.getPackageName())); }
}
