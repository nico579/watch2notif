package io.github.nico579.watch2notif;

import android.content.Context;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import java.util.concurrent.TimeUnit;

final class Scheduler {
    static void sync(Context context) {
        WorkManager manager = WorkManager.getInstance(context);
        if (Store.get(context).paused() || Store.get(context).feeds().stream().noneMatch(feed -> feed.enabled)) {
            manager.cancelUniqueWork("automatic-poll"); manager.cancelUniqueWork("initial-poll");
            new MonitoringState(context).stop();
            context.stopService(new android.content.Intent(context, LivePollService.class));
            return;
        }
        manager.enqueueUniquePeriodicWork("automatic-poll", ExistingPeriodicWorkPolicy.KEEP,
                new PeriodicWorkRequest.Builder(PollWorker.class, 15, TimeUnit.MINUTES)
                        .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build());
    }

    static void initialCheck(Context context) {
        if (Store.get(context).paused()) return;
        WorkManager.getInstance(context).enqueueUniqueWork("initial-poll", ExistingWorkPolicy.KEEP,
                new OneTimeWorkRequest.Builder(PollWorker.class)
                        .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build());
    }
}
