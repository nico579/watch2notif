package io.github.nico579.watch2notif;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

public final class PollWorker extends Worker {
    public PollWorker(@NonNull Context context, @NonNull WorkerParameters parameters) { super(context, parameters); }
    @NonNull @Override public Result doWork() {
        try {
            if (!Store.get(getApplicationContext()).paused()) new PollEngine(getApplicationContext()).poll(false);
            return Result.success();
        } catch (RuntimeException failure) { return Result.retry(); }
    }
}
