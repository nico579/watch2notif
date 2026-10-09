package io.github.nico579.watch2notif;

import android.content.Context;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletionService;
import java.util.concurrent.ExecutorCompletionService;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import static io.github.nico579.watch2notif.Models.*;

/** Read-only checks through the actual provider registry; never merges items or sends notifications. */
final class AccessSmokeTest {
    enum Outcome { PENDING, OK, FAILED, SKIPPED }
    interface Progress { void completed(Row row); }
    static final class Row {
        final int index;
        final String label, kind, error;
        final Outcome outcome;
        final int httpCode;
        Row(int index, String label, String kind, Outcome outcome, String error, int httpCode) {
            this.index = index; this.label = label; this.kind = kind; this.outcome = outcome; this.error = error; this.httpCode = httpCode;
        }
        Row finish(Outcome outcome, String error, int code) { return new Row(index, label, kind, outcome, error, code); }
    }
    private final Providers providers;
    private final AiFilter ai;
    private final Provider.Credentials credentials;
    private final long timeoutMillis;
    AccessSmokeTest(Context context, Network.Transport transport, Provider.Credentials credentials) { this(context, transport, credentials, 120000); }
    AccessSmokeTest(Context context, Network.Transport transport, Provider.Credentials credentials, long timeoutMillis) {
        providers = new Providers(context.getApplicationContext(), transport); ai = new AiFilter(transport);
        this.credentials = credentials; this.timeoutMillis = timeoutMillis;
    }
    static List<Row> rows(List<Feed> feeds) {
        List<Row> result = new ArrayList<>();
        for (Feed feed : feeds) result.add(new Row(result.size(), feed.label, feed.kind,
                feed.enabled ? Outcome.PENDING : Outcome.SKIPPED, feed.enabled ? "" : "disabled", 0));
        result.add(new Row(result.size(), "Claude", "claude", Outcome.PENDING, "", 0));
        return result;
    }
    List<Row> run(List<Feed> feeds, Progress progress) throws InterruptedException {
        List<Row> result = rows(feeds);
        ExecutorService pool = Executors.newFixedThreadPool(3, task -> { Thread thread = new Thread(task, "watch2notif-access-check"); thread.setDaemon(true); return thread; });
        CompletionService<Row> completion = new ExecutorCompletionService<>(pool);
        Map<Future<Row>, Row> pending = new HashMap<>();
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        try {
            for (int i = 0; i < feeds.size(); i++) {
                Feed feed = feeds.get(i); Row row = result.get(i);
                if (!feed.enabled) { progress.completed(row); continue; }
                pending.put(completion.submit(() -> {
                    try { providers.fetch(feed, credentials); return row.finish(Outcome.OK, "", 0); }
                    catch (Exception failure) { return failed(row, failure); }
                }), row);
            }
            Row claude = result.get(feeds.size());
            pending.put(completion.submit(() -> {
                try {
                    String key = credentials.get("claude");
                    boolean needed = feeds.stream().anyMatch(feed -> feed.enabled && !feed.filter.trim().isEmpty());
                    if (key.trim().isEmpty() && !needed) return claude.finish(Outcome.SKIPPED, "unused", 0);
                    ai.judge("This is a connection diagnostic. Classify the diagnostic message as relevant.",
                            new Entry("watch2notif-smoke", "Connection diagnostic", "watch2notif", "", "Test message only.", 0), key);
                    return claude.finish(Outcome.OK, "", 0);
                } catch (Exception failure) { return failed(claude, failure); }
            }), claude);
            while (!pending.isEmpty()) {
                long remaining = deadline - System.nanoTime();
                Future<Row> finished = remaining > 0 ? completion.poll(remaining, TimeUnit.NANOSECONDS) : null;
                if (finished == null) break;
                Row original = pending.remove(finished), row;
                try { row = finished.get(); }
                catch (java.util.concurrent.ExecutionException failure) { row = original.finish(Outcome.FAILED, "network", 0); }
                result.set(row.index, row); progress.completed(row);
            }
            for (Map.Entry<Future<Row>, Row> entry : pending.entrySet()) {
                entry.getKey().cancel(true);
                Row row = entry.getValue().finish(Outcome.FAILED, "timeout", 0);
                result.set(row.index, row); progress.completed(row);
            }
            return result;
        } finally { for (Future<Row> future : pending.keySet()) future.cancel(true); pool.shutdownNow(); }
    }
    private static Row failed(Row row, Exception failure) {
        SourceException fixed = failure instanceof SourceException ? (SourceException)failure : new SourceException("storage");
        return row.finish(Outcome.FAILED, fixed.code, fixed.httpStatus);
    }
}
