package io.github.nico579.watch2notif;

import android.app.Application;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ServiceController;
import org.robolectric.annotation.Config;
import java.io.File;
import java.lang.reflect.Field;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = {26, 34}, application = Application.class)
public class MonitoringTest {
    private Context context;
    private Store store;
    private MonitoringState state;

    public static class ControlledService extends LivePollService {
        int checks, loops;
        boolean fail;
        @Override java.util.concurrent.ScheduledExecutorService createExecutor() {
            return new java.util.concurrent.ScheduledThreadPoolExecutor(1) {
                @Override public java.util.concurrent.ScheduledFuture<?> scheduleWithFixedDelay(Runnable work, long initial, long delay, java.util.concurrent.TimeUnit unit) {
                    loops++; return null;
                }
            };
        }
        @Override PollEngine.Report checkSources() {
            checks++;
            if (fail) throw new IllegalStateException("simulated storage failure");
            PollEngine.Report report = new PollEngine.Report(); report.checked = report.succeeded = 1; return report;
        }
    }

    @Before public void reset() throws Exception {
        context = RuntimeEnvironment.getApplication();
        Field singleton = Store.class.getDeclaredField("instance"); singleton.setAccessible(true); singleton.set(null, null);
        File saved = new File(context.getFilesDir(), "watch2notif.json"); if (saved.exists()) assertTrue(saved.delete());
        context.getSharedPreferences("monitoring", Context.MODE_PRIVATE).edit().clear().commit();
        LivePollService.running = false; Notifications.channels(context);
        store = Store.get(context); store.putFeed(new Models.Feed("test", "Test", "rss", "https://example.org/feed", 60, true));
        state = new MonitoringState(context);
    }

    private MonitorWakeLock wake(LivePollService service) throws Exception {
        Field field = LivePollService.class.getDeclaredField("wake"); field.setAccessible(true); return (MonitorWakeLock)field.get(service);
    }

    @Test public void nullRestartRequiresPreviouslyRequestedMonitoring() throws Exception {
        ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get();
        assertEquals(Service.START_NOT_STICKY, service.onStartCommand(null, 0, 1));
        assertFalse(LivePollService.running); assertNull(wake(service)); assertEquals(0, service.loops);
        controller.destroy();
    }

    @Test public void requestedSessionIsStickyAndResumesWithTheSameSourceState() throws Exception {
        Models.Feed feed = store.find("test"); Models.PollState baseline = store.state(feed);
        baseline.merge(java.util.List.of(new Models.Entry("base", "Base", "", "", "", 0)), 1); store.state(feed, baseline);
        state.request();
        ServiceController<ControlledService> first = Robolectric.buildService(ControlledService.class).create();
        assertEquals(Service.START_STICKY, first.get().onStartCommand(new Intent(), 0, 1));
        assertTrue(LivePollService.running); assertTrue(wake(first.get()).held());
        first.get().tick(); assertEquals(1, state.cycles()); first.destroy();
        assertTrue(state.requested()); assertFalse(wake(first.get()).held());
        ServiceController<ControlledService> restarted = Robolectric.buildService(ControlledService.class).create();
        assertEquals(Service.START_STICKY, restarted.get().onStartCommand(null, 0, 2));
        assertTrue(wake(restarted.get()).held()); assertTrue(store.state(feed).seen.contains("base"));
        restarted.destroy(); assertFalse(wake(restarted.get()).held());
    }

    @Test public void repeatedStartsDoNotCreateAdditionalLoops() {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get();
        assertEquals(Service.START_STICKY, service.onStartCommand(new Intent(), 0, 1));
        assertEquals(Service.START_STICKY, service.onStartCommand(new Intent(), 0, 2));
        assertEquals(1, service.loops); controller.destroy();
    }

    @Test public void notificationStopClearsRequestAndReleasesCpuImmediately() throws Exception {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get(); service.onStartCommand(new Intent(), 0, 1);
        assertEquals(Service.START_NOT_STICKY, service.onStartCommand(new Intent().setAction(LivePollService.STOP), 0, 2));
        assertFalse(state.requested()); assertFalse(wake(service).held()); assertFalse(LivePollService.running);
        service.tick(); assertEquals(0, service.checks); controller.destroy();
    }

    @Test public void pausingStopsTheLoopWithoutLosingSourceHistory() throws Exception {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get(); service.onStartCommand(new Intent(), 0, 1);
        store.paused(true); service.tick();
        assertFalse(state.requested()); assertFalse(wake(service).held()); assertEquals(0, service.checks);
        assertEquals(1, store.feeds().size()); controller.destroy();
    }

    @Test public void disablingEverySourceStopsTheLoop() throws Exception {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get(); service.onStartCommand(new Intent(), 0, 1);
        store.putFeed(store.find("test").withEnabled(false)); service.tick();
        assertFalse(state.requested()); assertFalse(wake(service).held()); assertEquals(0, service.checks); controller.destroy();
    }

    @Test public void timeoutLeavesAnExplicitInterruptionAndCannotRestartItself() throws Exception {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get(); service.onStartCommand(new Intent(), 0, 1);
        service.onTimeout(1, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        assertTrue(state.requested()); assertEquals(MonitoringState.LIMIT, state.interruption());
        assertFalse(wake(service).held()); assertFalse(LivePollService.running); controller.destroy();
        ServiceController<ControlledService> restart = Robolectric.buildService(ControlledService.class).create();
        assertEquals(Service.START_NOT_STICKY, restart.get().onStartCommand(null, 0, 2));
        assertEquals(0, restart.get().loops); restart.destroy();
        assertTrue(context.getSystemService(NotificationManager.class).getActiveNotifications().length > 0);
        assertFalse(store.paused());
    }

    @Test public void runtimeFailureCannotSilentlyCancelFutureChecksOrLeakWakeLock() throws Exception {
        state.request(); ServiceController<ControlledService> controller = Robolectric.buildService(ControlledService.class).create();
        ControlledService service = controller.get(); service.onStartCommand(new Intent(), 0, 1); service.fail = true; service.tick();
        assertEquals(MonitoringState.UNAVAILABLE, state.interruption()); assertFalse(wake(service).held());
        assertFalse(LivePollService.running); assertEquals(0, state.lastCycle()); controller.destroy();
    }

    @Test public void closedWakeLockCannotBeReacquiredByAnOldWorker() {
        MonitorWakeLock wake = new MonitorWakeLock(context); wake.renew(); assertTrue(wake.held());
        wake.close(); wake.renew(); assertFalse(wake.held()); wake.close();
    }

    @Test public void healthSkipsBusyPassesAndLimitsEmptyHeartbeatWrites() {
        state.request(); PollEngine.Report checked = new PollEngine.Report(); checked.checked = 2; checked.succeeded = 1; checked.failed = 1;
        state.completed(checked, 100000); assertEquals(1, new MonitoringState(context).cycles());
        PollEngine.Report empty = new PollEngine.Report(); state.completed(empty, 105000); assertEquals(1, state.cycles());
        empty.busy = true; state.completed(empty, 165000); assertEquals(1, state.cycles());
        empty.busy = false; state.completed(empty, 165000); assertEquals(2, state.cycles());
        assertEquals(1, state.succeeded()); assertEquals(1, state.failed());
        state.stop(); state.completed(checked, 200000); assertEquals(2, state.cycles());
    }

    @Test public void monitoringIntentAndHealthAreNotPartOfPortableExports() throws Exception {
        state.request(); assertTrue(new MonitoringState(context).requested());
        assertFalse(store.exportConfig().has("requested")); assertFalse(store.exportConfig().has("last_cycle"));
    }
}
