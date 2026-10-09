package io.github.nico579.watch2notif;

import android.content.Context;
import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.BooleanSupplier;
import static io.github.nico579.watch2notif.Models.*;

final class PollEngine {
    private static final ReentrantLock POLL_LOCK = new ReentrantLock();
    interface AlertSender { boolean send(Context context, Feed feed, Entry entry); }
    interface Credentials extends Provider.Credentials { }
    static final class Report { int checked, succeeded, failed, sent, filtered; boolean busy; }
    private final Context context;
    private final Store store;
    private final Providers providers;
    private final AiFilter filter;
    private final AlertSender sender;
    private final Credentials credentials;
    private final BooleanSupplier mayNotify;

    PollEngine(Context context) {
        this(context, Store.get(context), new Network.HttpTransport(), Notifications::send);
    }

    PollEngine(Context context, Store store, Network.Transport network, AlertSender sender) {
        this(context, store, network, sender, new SecretStore(context)::get, () -> Notifications.allowed(context));
    }

    PollEngine(Context context, Store store, Network.Transport network, AlertSender sender, Credentials credentials, BooleanSupplier mayNotify) {
        this.context = Localisation.context(context); this.store = store;
        this.providers = new Providers(this.context, network); this.filter = new AiFilter(network); this.sender = sender;
        this.credentials = credentials; this.mayNotify = mayNotify;
    }

    Report poll(boolean manual) {
        Report report = new Report();
        if (!POLL_LOCK.tryLock()) { report.busy = true; return report; }
        try {
            long deadline = System.nanoTime() + 480000000000L;
            for (Feed snapshot : store.feeds()) {
                if (System.nanoTime() > deadline || Thread.currentThread().isInterrupted()) break;
                synchronized (store) {
                    if (!store.current(snapshot, manual)) continue;
                    PollState state = store.state(snapshot);
                    long elapsed = System.currentTimeMillis() - state.lastAttempt;
                    if (!manual && elapsed >= 0 && elapsed < snapshot.interval * 1000L) continue;
                }
                report.checked++;
                try {
                    List<Entry> entries = providers.fetch(snapshot, credentials);
                    synchronized (store) {
                        if (!store.current(snapshot, manual)) continue;
                        PollState state = store.state(snapshot);
                        state.merge(entries, System.currentTimeMillis()); state.lastAttempt = state.lastSuccess = System.currentTimeMillis();
                        state.error = ""; state.httpCode = 0; store.state(snapshot, state);
                    }
                    deliver(snapshot, manual, deadline, report);
                    report.succeeded++;
                } catch (Exception failure) {
                    report.failed++;
                    synchronized (store) {
                        if (!store.current(snapshot, manual)) continue;
                        PollState state = store.state(snapshot); state.lastAttempt = System.currentTimeMillis();
                        SourceException source = failure instanceof SourceException ? (SourceException)failure : new SourceException(failure instanceof IOException ? "storage" : "network");
                        state.error = source.code; state.httpCode = source.httpStatus;
                        try { store.state(snapshot, state); } catch (IOException ignored) { }
                    }
                    // Previously fetched pending items remain deliverable even when the source is now offline.
                    try { deliver(snapshot, manual, deadline, report); } catch (Exception ignored) { }
                }
                WatchApp.updated(context);
            }
            return report;
        } finally { POLL_LOCK.unlock(); WatchApp.updated(context); }
    }

    private void deliver(Feed snapshot, boolean manual, long deadline, Report report) throws Exception {
        List<Entry> pending;
        synchronized (store) { pending = new ArrayList<>(store.state(snapshot).pending.values()); }
        Collections.reverse(pending);
        for (Entry entry : pending) {
            if (System.nanoTime() > deadline || Thread.currentThread().isInterrupted() || !mayNotify.getAsBoolean()) break;
            Feed current;
            JSONObject cached;
            synchronized (store) {
                if (!store.current(snapshot, manual)) break;
                current = store.find(snapshot.key);
                cached = store.state(snapshot).decisions.optJSONObject(entry.id);
            }
            String ruleHash = hash(current.filter), reason = "";
            AiFilter.Verdict verdict = null;
            if (!current.filter.trim().isEmpty()) {
                if (cached != null && ruleHash.equals(cached.optString("rule"))) {
                    verdict = new AiFilter.Verdict(cached.getBoolean("relevant"), cached.optString("reason"));
                } else {
                    try { verdict = filter.judge(current.filter, entry, credentials.get("claude")); }
                    catch (Exception unavailable) {
                        reason = context.getString(unavailable instanceof SourceException && "claude_key".equals(((SourceException)unavailable).code)
                                ? R.string.ai_missing_fallback : R.string.ai_unavailable);
                    }
                }
                if (verdict != null) reason = verdict.reason;
            }
            synchronized (store) {
                if (!store.current(snapshot, manual)) break;
                Feed latest = store.find(snapshot.key);
                if (!latest.filter.equals(current.filter)) continue; // Re-evaluate a changed rule on the next pass.
                PollState state = store.state(snapshot);
                if (!state.pending.containsKey(entry.id)) continue;
                if (verdict != null) {
                    if (!verdict.relevant) {
                        state.delivered(entry.id); store.state(latest, state); report.filtered++; continue;
                    }
                    state.decisions.put(entry.id, new JSONObject().put("rule", ruleHash).put("relevant", true).put("reason", reason));
                    store.state(latest, state);
                }
                Entry alert = reason.trim().isEmpty() ? entry : new Entry(entry.id, entry.title, entry.author, entry.link,
                        reason + " | " + entry.summary, entry.created);
                if (sender.send(context, latest, alert)) { store.delivered(latest, state, alert); report.sent++; }
            }
        }
    }
}
