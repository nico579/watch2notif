package io.github.nico579.watch2notif;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.List;
import static org.junit.Assert.*;

/** Prepares only a disposable GitHub emulator. The external ADB smoke runs without instrumentation. */
@RunWith(AndroidJUnit4.class)
public class MonitoringFixtureTest {
    @Test public void prepareLocalFixture() throws Exception {
        assertTrue("Only debug builds may prepare emulator data", BuildConfig.DEBUG);
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Store store = Store.get(context);
        store.replaceFeeds(List.of(new Models.Feed("ci-monitoring", "CI local RSS", "rss", "http://127.0.0.1:29089/rss", 5, true)));
        store.paused(false);
        context.getSharedPreferences("monitoring", Context.MODE_PRIVATE).edit().clear().commit();
        new MonitoringState(context).request();
        Scheduler.sync(context);
        assertEquals(1, store.feeds().size());
        assertTrue(new MonitoringState(context).requested());
    }
}
