package io.github.nico579.watch2notif;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.ClipData;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.DateFormat;
import java.util.Date;
import java.util.List;
import java.util.UUID;
import static io.github.nico579.watch2notif.Models.*;

public final class MainActivity extends Activity {
    private static final int IMPORT = 10, EXPORT = 11, PERMISSION = 12, UPDATE_PERMISSION = 13, UPDATE_INSTALL = 14, BATTERY = 15;
    private Store store;
    private LinearLayout root, content;
    private ScrollView scroll;
    private int selectedTab;
    private boolean refreshing, receiverRegistered;
    private String exportDocument;
    private PairingSession pairing;
    private AlertDialog pairingDialog;
    private PairingSession.State pairingDialogState;
    private boolean resumed;
    private UpdateSession appUpdates;
    private UpdateSession.State displayedUpdateState;
    private TextView updateStatus, smokeSummary;
    private TextView monitoringStatus, batteryStatus;
    private Button updateAction, updateCheck, updateCancel;
    private SmokeSession smoke;
    private AlertDialog smokeDialog;
    private LinearLayout smokeRows;
    private static final class Retained {
        final PairingSession pairing;
        final UpdateSession updates;
        final SmokeSession smoke;
        Retained(PairingSession pairing, UpdateSession updates, SmokeSession smoke) { this.pairing = pairing; this.updates = updates; this.smoke = smoke; }
    }
    private final BroadcastReceiver updates = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { if (selectedTab != 2) render(); else monitoringControls(); }
    };

    @Override protected void attachBaseContext(Context base) { super.attachBaseContext(Localisation.context(base)); }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        Retained retained = (Retained) getLastNonConfigurationInstance();
        if (retained != null) { pairing = retained.pairing; appUpdates = retained.updates; smoke = retained.smoke; }
        else appUpdates = new UpdateSession(getApplicationContext());
        if (state != null) { selectedTab = state.getInt("tab"); exportDocument = state.getString("export_document"); }
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(color(R.color.background));
        try { store = Store.get(this); render(); }
        catch (RuntimeException error) {
            TextView message = text(getString(R.string.error_storage), 18, R.color.warning);
            message.setPadding(dp(24), dp(64), dp(24), dp(24)); setContentView(message);
        }
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        if (store == null) return;
        if (!receiverRegistered) {
            ContextCompat.registerReceiver(this, updates, new IntentFilter(WatchApp.UPDATED), ContextCompat.RECEIVER_NOT_EXPORTED);
            receiverRegistered = true;
        }
        if (getApplication() instanceof WatchApp) MonitoringState.resumeVisible(this);
        if (selectedTab != 2) render(); else monitoringControls();
        if (pairing != null) pairing.attach(this::showPairing);
        if (smoke != null) smoke.attach(this::showSmoke);
        appUpdates.attach(this::updateChanged);
        // Only the real application schedules automatic checks; preview/test activities stay offline.
        if (getApplication() instanceof WatchApp) appUpdates.check(false);
    }

    @Override protected void onPause() {
        resumed = false;
        if (pairing != null) pairing.detach();
        if (smoke != null) smoke.detach();
        appUpdates.detach(); dismissSmokeDialog();
        dismissPairingDialog();
        if (receiverRegistered) { unregisterReceiver(updates); receiverRegistered = false; }
        super.onPause();
    }

    @Override public Object onRetainNonConfigurationInstance() { return new Retained(pairing, appUpdates, smoke); }

    @Override protected void onDestroy() {
        if (pairing != null && !isChangingConfigurations()) pairing.close();
        if (!isChangingConfigurations()) { appUpdates.close(); if (smoke != null) smoke.close(); }
        dismissSmokeDialog();
        dismissPairingDialog();
        super.onDestroy();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putInt("tab", selectedTab); state.putString("export_document", exportDocument);
        super.onSaveInstanceState(state);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private int color(int id) { return getColor(id); }
    private LinearLayout column() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL); return view; }
    private LinearLayout row() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.HORIZONTAL); view.setGravity(Gravity.CENTER_VERTICAL); return view; }
    private LinearLayout.LayoutParams space(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(top); return params;
    }
    private TextView text(String value, int size, int colorId) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color(colorId));
        view.setLineSpacing(dp(3), 1); return view;
    }
    private TextView heading(String value, int size) { TextView view = text(value, size, R.color.foreground); view.setTypeface(null, Typeface.BOLD); return view; }
    private GradientDrawable background(int fill, int border) {
        GradientDrawable drawable = new GradientDrawable(); drawable.setColor(color(fill)); drawable.setCornerRadius(dp(16));
        drawable.setStroke(dp(1), color(border)); return drawable;
    }
    private Button button(int label, boolean primary, View.OnClickListener listener) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false); button.setTextSize(14);
        button.setTextColor(primary ? color(R.color.background) : color(R.color.foreground));
        button.setBackground(background(primary ? R.color.accent : R.color.surface, primary ? R.color.accent : R.color.border));
        button.setPadding(dp(12), dp(10), dp(12), dp(10)); button.setMinHeight(dp(48));
        button.setOnClickListener(listener); return button;
    }
    private void addButton(LinearLayout parent, int label, boolean primary, View.OnClickListener listener) { parent.addView(button(label, primary, listener), space(12)); }
    private LinearLayout card() {
        LinearLayout view = column(); view.setBackground(background(R.color.surface, R.color.border));
        view.setPadding(dp(18), dp(18), dp(18), dp(18)); content.addView(view, space(12)); return view;
    }
    private void note(LinearLayout parent, int label) { parent.addView(text(getString(label), 13, R.color.muted), space(10)); }
    private EditText field(LinearLayout parent, int label, String value, boolean password) {
        parent.addView(text(getString(label), 13, R.color.muted), space(14));
        EditText input = new EditText(this); input.setText(value); input.setTextSize(16); input.setSingleLine(true);
        input.setInputType(password ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_CLASS_TEXT);
        input.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        parent.addView(input, space(2)); return input;
    }

    private void render() {
        if (store == null || isFinishing() || isDestroyed()) return;
        int previousScroll = scroll == null ? 0 : scroll.getScrollY();
        root = column(); root.setBackgroundColor(color(R.color.background));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets padding = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                root.setPadding(padding.left, padding.top, padding.right, padding.bottom);
            } else root.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout header = row(); header.setPadding(dp(20), dp(20), dp(20), dp(16));
        ImageView logo = new ImageView(this); logo.setImageResource(R.mipmap.ic_launcher); logo.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        header.addView(logo, new LinearLayout.LayoutParams(dp(42), dp(42)));
        LinearLayout titles = column(); titles.setPadding(dp(12), 0, 0, 0);
        titles.addView(heading("watch2notif", 24)); titles.addView(text(getString(R.string.tagline), 12, R.color.muted));
        header.addView(titles, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1)); root.addView(header);
        LinearLayout tabs = row(); tabs.setPadding(dp(16), 0, dp(16), dp(8));
        int[] labels = {R.string.sources, R.string.history, R.string.settings};
        for (int i = 0; i < labels.length; i++) {
            final int tab = i;
            Button navigation = button(labels[i], i == selectedTab, view -> { selectedTab = tab; scroll = null; render(); });
            navigation.setSelected(i == selectedTab);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
            if (i > 0) params.setMarginStart(dp(6)); tabs.addView(navigation, params);
        }
        root.addView(tabs); scroll = new ScrollView(this); scroll.setFillViewport(true);
        content = column(); content.setPadding(dp(16), 0, dp(16), dp(28)); scroll.addView(content);
        updateStatus = null; updateAction = updateCheck = updateCancel = null;
        monitoringStatus = batteryStatus = null;
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        if (selectedTab != 2 && (appUpdates.state == UpdateSession.State.AVAILABLE || appUpdates.state == UpdateSession.State.READY)) {
            LinearLayout available = card(); available.addView(text(getString(R.string.update_available, appUpdates.release.version), 14, R.color.accent));
            addButton(available, R.string.updates, true, view -> { selectedTab = 2; scroll = null; render(); });
        }
        if (selectedTab == 0) sources(); else if (selectedTab == 1) history(); else settings();
        setContentView(root); root.requestApplyInsets();
        scroll.post(() -> scroll.scrollTo(0, previousScroll));
    }

    private void sources() {
        MonitoringState monitoring = new MonitoringState(this);
        LinearLayout status = card(); status.addView(text(getString(R.string.monitoring).toUpperCase(getResources().getConfiguration().getLocales().get(0)), 12, R.color.muted));
        status.addView(heading(getString(store.paused() ? R.string.paused : LivePollService.running ? R.string.live
                : monitoring.requested() ? R.string.live_interrupted : R.string.automatic), 19), space(8));
        List<Feed> feeds = store.feeds(); long active = feeds.stream().filter(feed -> feed.enabled).count();
        status.addView(text(getString(R.string.source_count, active, feeds.size()), 14, R.color.success), space(8));
        addButton(status, store.paused() ? R.string.resume : R.string.pause, false, view -> changePause());
        Button refresh = button(refreshing ? R.string.checking : R.string.refresh, true, view -> refresh());
        refresh.setEnabled(!refreshing && active > 0); status.addView(refresh, space(12));
        Button live = button(LivePollService.running ? R.string.stop_live : R.string.start_live, false, view -> toggleLive());
        live.setEnabled(active > 0 && !store.paused()); status.addView(live, space(12)); note(status, R.string.background_note);
        if (monitoring.requested() && !LivePollService.running) {
            note(status, MonitoringState.LIMIT.equals(monitoring.interruption()) ? R.string.live_limit : R.string.live_unavailable);
            addButton(status, R.string.stop_live, false, view -> stopLive());
        }
        if (LivePollService.running || monitoring.requested()) {
            status.addView(text(getString(MonitoringState.batteryUnrestricted(this) ? R.string.battery_allowed : R.string.battery_restricted),
                    13, MonitoringState.batteryUnrestricted(this) ? R.color.success : R.color.warning), space(10));
            if (!MonitoringState.batteryUnrestricted(this)) addButton(status, R.string.battery_settings, false, view -> batterySettings());
        }
        if (monitoring.lastCycle() > 0) status.addView(text(getString(R.string.live_last_cycle, date(monitoring.lastCycle()), monitoring.cycles()), 12, R.color.muted), space(8));
        if (!Notifications.allowed(this)) {
            LinearLayout notice = card(); notice.addView(text(getString(R.string.notifications_denied), 14, R.color.warning));
            addButton(notice, R.string.allow_notifications, false, view -> notificationPermission());
        }
        addButton(content, R.string.add_source, true, view -> edit(null));
        if (feeds.isEmpty()) {
            LinearLayout empty = card(); empty.addView(heading(getString(R.string.no_sources), 20)); note(empty, R.string.no_sources_body);
        }
        for (Feed feed : feeds) {
            LinearLayout card = card(), top = row();
            TextView title = heading(feed.label, 18); top.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            Switch enabled = new Switch(this); enabled.setContentDescription(feed.label + " · " + getString(R.string.source_enabled)); enabled.setChecked(feed.enabled);
            enabled.setOnCheckedChangeListener((control, value) -> {
                try { store.putFeed(feed.withEnabled(value)); Scheduler.sync(this); if (value) Scheduler.initialCheck(this); render(); }
                catch (Exception failure) { toast(R.string.error_storage); }
            });
            top.addView(enabled); card.addView(top);
            card.addView(text(getString(LABELS[kindIndex(feed.kind)]) + " · " + feed.interval + " s", 12, R.color.accent), space(6));
            String address = feed.url;
            if (feed.kind.equals("rss")) { Uri uri = Uri.parse(address); address = uri.getHost() + (uri.getPath() == null ? "" : uri.getPath()); }
            card.addView(text(address, 13, R.color.muted), space(6));
            PollState state = store.state(feed);
            String message = !feed.enabled ? getString(R.string.source_disabled) : state.lastAttempt == 0 ? getString(R.string.never_checked)
                    : getString(R.string.last_checked, date(state.lastAttempt));
            card.addView(text(message, 12, R.color.muted), space(10));
            if (!state.error.isEmpty()) card.addView(text(getString(SourceException.message(state.error, state.httpCode), state.httpCode), 13, R.color.warning), space(6));
            else if (state.lastSuccess > 0) card.addView(text(getString(R.string.source_access_ok, date(state.lastSuccess)), 12, R.color.success), space(6));
            if (!state.pending.isEmpty()) card.addView(text(getString(R.string.pending_notifications, state.pending.size()), 13, R.color.warning), space(6));
            if (!feed.filter.trim().isEmpty()) {
                card.addView(text(getString(R.string.ai_filter_active), 12, R.color.accent), space(6));
                try { if (new SecretStore(this).get("claude").trim().isEmpty()) card.addView(text(getString(R.string.ai_key_missing), 13, R.color.warning), space(6)); }
                catch (Exception failure) { card.addView(text(getString(R.string.credentials_failed), 13, R.color.warning), space(6)); }
            }
            addButton(card, R.string.edit_source, false, view -> edit(feed));
        }
    }

    private void changePause() {
        try { store.paused(!store.paused()); Scheduler.sync(this); if (!store.paused()) Scheduler.initialCheck(this); render(); }
        catch (Exception failure) { toast(R.string.error_storage); }
    }

    private void refresh() {
        if (refreshing) return; refreshing = true; render();
        WatchApp.IO.execute(() -> {
            PollEngine.Report report = new PollEngine(this).poll(true);
            runOnUiThread(() -> {
                refreshing = false;
                if (!isDestroyed()) {
                    Toast.makeText(this, report.busy ? getString(R.string.check_busy) : getString(R.string.check_result, report.succeeded, report.failed, report.sent)
                            + (report.filtered > 0 ? "\n" + getString(R.string.check_filtered, report.filtered) : ""), Toast.LENGTH_LONG).show(); render();
                }
            });
        });
    }

    private void toggleLive() {
        if (LivePollService.running) { stopLive(); return; }
        if (!Notifications.allowed(this)) { notificationPermission(); return; }
        new AlertDialog.Builder(this).setTitle(R.string.start_live).setMessage(R.string.live_explanation)
                .setNegativeButton(R.string.cancel, null).setPositiveButton(R.string.start_live, (dialog, which) -> {
                    if (!MonitoringState.start(this)) toast(R.string.live_unavailable);
                }).show();
    }

    private void stopLive() {
        new MonitoringState(this).stop(); stopService(new Intent(this, LivePollService.class));
        Notifications.clearMonitoringInterruption(this); render();
    }

    private void batterySettings() {
        try {
            Intent intent = MonitoringState.batteryUnrestricted(this)
                    ? new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                    : new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getPackageName()));
            startActivityForResult(intent, BATTERY);
        } catch (ActivityNotFoundException unavailable) {
            try { startActivityForResult(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())), BATTERY); }
            catch (ActivityNotFoundException missingSettings) { toast(R.string.battery_settings_unavailable); }
        }
    }

    private void monitoringCard() {
        LinearLayout monitoring = card(); monitoring.addView(heading(getString(R.string.background_monitoring), 18));
        monitoringStatus = text("", 14, R.color.foreground); monitoring.addView(monitoringStatus, space(10));
        batteryStatus = text("", 14, R.color.foreground); monitoring.addView(batteryStatus, space(10));
        note(monitoring, R.string.battery_explanation);
        addButton(monitoring, R.string.battery_settings, false, view -> batterySettings());
        if (Build.VERSION.SDK_INT >= 35) note(monitoring, R.string.live_limit_note);
        monitoringControls();
    }

    private void monitoringControls() {
        if (batteryStatus == null || monitoringStatus == null) return;
        boolean unrestricted = MonitoringState.batteryUnrestricted(this);
        batteryStatus.setText(unrestricted ? R.string.battery_allowed : R.string.battery_restricted);
        batteryStatus.setTextColor(color(unrestricted ? R.color.success : R.color.warning));
        MonitoringState state = new MonitoringState(this);
        String description = getString(store.paused() ? R.string.paused : LivePollService.running ? R.string.live
                : state.requested() ? R.string.live_interrupted : R.string.automatic);
        if (state.requested() && !LivePollService.running) description += "\n" + getString(MonitoringState.LIMIT.equals(state.interruption()) ? R.string.live_limit : R.string.live_unavailable);
        if (state.lastCycle() > 0) description += "\n" + getString(R.string.live_last_cycle, date(state.lastCycle()), state.cycles())
                + "\n" + getString(R.string.live_cycle_result, state.succeeded(), state.failed());
        monitoringStatus.setText(description);
    }

    private void notificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
                && !getPreferences(MODE_PRIVATE).getBoolean("notification_permission_asked", false)) {
            getPreferences(MODE_PRIVATE).edit().putBoolean("notification_permission_asked", true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, PERMISSION);
        } else {
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results); render();
    }

    private void edit(Feed existing) {
        LinearLayout form = column(); form.setPadding(dp(20), dp(4), dp(20), dp(20));
        EditText name = field(form, R.string.source_name, existing == null ? "" : existing.label, false);
        form.addView(text(getString(R.string.source_type), 13, R.color.muted), space(14));
        Spinner kind = new Spinner(this); String[] options = new String[KINDS.length];
        for (int i = 0; i < options.length; i++) options[i] = getString(LABELS[i]);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, options);
        kind.setAdapter(adapter); kind.setSelection(existing == null ? 0 : kindIndex(existing.kind)); form.addView(kind, space(2));
        EditText address = field(form, R.string.source_address, existing == null ? "" : existing.url, false);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        EditText interval = field(form, R.string.source_interval, String.valueOf(existing == null ? 60 : existing.interval), false);
        interval.setInputType(InputType.TYPE_CLASS_NUMBER);
        Switch enabled = new Switch(this); enabled.setText(R.string.source_enabled); enabled.setChecked(existing == null || existing.enabled); form.addView(enabled, space(14));
        EditText rule = field(form, R.string.ai_filter, existing == null ? "" : existing.filter, false);
        rule.setSingleLine(false); rule.setMinLines(2); rule.setMaxLines(5); rule.setGravity(Gravity.TOP | Gravity.START); rule.setHint(R.string.ai_filter_hint);
        rule.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        note(form, R.string.ai_filter_note);
        final int[] previousKind = {kind.getSelectedItemPosition()};
        address.setHint(HINTS[previousKind[0]]);
        kind.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                address.setHint(HINTS[position]);
                if (position != previousKind[0]) interval.setText(String.valueOf(defaultInterval(KINDS[position])));
                previousKind[0] = position;
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        ScrollView scroller = new ScrollView(this); scroller.addView(form);
        AlertDialog.Builder builder = new AlertDialog.Builder(this).setTitle(existing == null ? R.string.add_source : R.string.edit_source)
                .setView(scroller).setNegativeButton(R.string.cancel, null).setPositiveButton(R.string.save, null);
        if (existing != null) builder.setNeutralButton(R.string.delete, (dialog, which) -> new AlertDialog.Builder(this)
                .setMessage(getString(R.string.delete_source_question, existing.label)).setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.delete, (confirmation, item) -> {
                    try { store.deleteFeed(existing.key); Scheduler.sync(this); render(); } catch (Exception failure) { toast(R.string.error_storage); }
                }).show());
        AlertDialog dialog = builder.create(); dialog.setOnShowListener(shown -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            try {
                Feed feed = new Feed(existing == null ? UUID.randomUUID().toString() : existing.key, name.getText().toString(),
                        KINDS[kind.getSelectedItemPosition()], address.getText().toString(), Integer.parseInt(interval.getText().toString()),
                        enabled.isChecked(), rule.getText().toString());
                store.putFeed(feed); Scheduler.sync(this); Scheduler.initialCheck(this); dialog.dismiss(); render();
            } catch (IllegalArgumentException failure) { toast(existing == null && store.feeds().size() >= MAX_SOURCES ? R.string.source_limit : R.string.invalid_source); }
            catch (Exception failure) { toast(R.string.error_storage); }
        })); dialog.show();
    }

    private void history() {
        note(content, R.string.history_note);
        JSONArray rows = store.history();
        if (rows.length() == 0) {
            LinearLayout empty = card(); empty.addView(heading(getString(R.string.empty_history), 20)); note(empty, R.string.empty_history_body); return;
        }
        addButton(content, R.string.clear_history, false, view -> new AlertDialog.Builder(this).setMessage(R.string.clear_history_question)
                .setNegativeButton(R.string.cancel, null).setPositiveButton(R.string.clear_history, (dialog, which) -> {
                    try { store.clearHistory(); render(); } catch (Exception failure) { toast(R.string.error_storage); }
                }).show());
        for (int i = 0; i < rows.length(); i++) {
            JSONObject item = rows.optJSONObject(i); if (item == null) continue;
            LinearLayout card = card(); card.addView(text(str(item, "feed_label", "") + " · " + date((long)(item.optDouble("timestamp") * 1000)), 12, R.color.accent));
            card.addView(heading(str(item, "title", getString(R.string.untitled)), 17), space(6));
            card.addView(text(str(item, "author", "") + " · " + compact(str(item, "summary", ""), 400), 14, R.color.muted), space(6));
            card.setOnClickListener(view -> openLink(str(item, "link", ""))); card.setFocusable(true);
            addButton(card, R.string.remove_history_line, false, view -> {
                try { store.removeHistory(item); render(); } catch (Exception failure) { toast(R.string.error_storage); }
            });
        }
    }

    private void settings() {
        LinearLayout pairing = card(); pairing.addView(heading(getString(R.string.pair_title), 18)); note(pairing, R.string.pair_note);
        addButton(pairing, R.string.pair_receive, true, view -> new IntentIntegrator(this)
                .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE).setPrompt(getString(R.string.pair_scan))
                .setBeepEnabled(false).setOrientationLocked(false).initiateScan());
        updateCard();
        monitoringCard();
        LinearLayout language = card(); language.addView(heading(getString(R.string.language), 18));
        Spinner selector = new Spinner(this); String[] languages = {getString(R.string.language_system), "Français", "English"};
        selector.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, languages));
        selector.setSelection(store.language().equals("fr") ? 1 : store.language().equals("en") ? 2 : 0); language.addView(selector, space(8));
        selector.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String value = position == 1 ? "fr" : position == 2 ? "en" : "";
                if (!value.equals(store.language())) {
                    try { store.language(value); Notifications.channels(MainActivity.this); recreate(); } catch (Exception failure) { toast(R.string.error_storage); }
                }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        LinearLayout credentials = card(); credentials.addView(heading(getString(R.string.credentials), 18)); note(credentials, R.string.credentials_note);
        String github = "", youtube = "", claude = "";
        SecretStore secret = new SecretStore(this);
        try { github = secret.get("github"); youtube = secret.get("youtube"); claude = secret.get("claude"); }
        catch (Exception failure) { credentials.addView(text(getString(R.string.credentials_failed), 14, R.color.warning), space(8)); }
        EditText githubField = field(credentials, R.string.github_token, github, true), youtubeField = field(credentials, R.string.youtube_key, youtube, true);
        EditText claudeField = field(credentials, R.string.claude_key, claude, true);
        addButton(credentials, R.string.save_credentials, true, view -> {
            try { secret.save(githubField.getText().toString(), youtubeField.getText().toString(), claudeField.getText().toString()); toast(R.string.saved); }
            catch (Exception failure) { toast(R.string.credentials_failed); }
        });
        note(credentials, R.string.smoke_note);
        addButton(credentials, R.string.smoke_title, false, view -> {
            if (smoke == null) smoke = new SmokeSession(getApplicationContext(), store.feeds());
            smoke.attach(this::showSmoke);
        });
        LinearLayout config = card(); config.addView(heading(getString(R.string.configuration), 18)); note(config, R.string.import_note);
        addButton(config, R.string.import_config, false, view -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                    .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/json", "text/plain", "application/octet-stream"});
            try { startActivityForResult(intent, IMPORT); } catch (ActivityNotFoundException failure) { toast(R.string.file_error); }
        });
        addButton(config, R.string.export_config, false, view -> {
            try {
                exportDocument = store.exportConfig().toString(2);
                startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("application/json").putExtra(Intent.EXTRA_TITLE, "watch2notif-config.json"), EXPORT);
            } catch (Exception failure) { toast(R.string.file_error); }
        });
        addButton(config, R.string.notification_settings, false, view -> notificationPermission());
        LinearLayout about = card(); about.addView(heading(getString(R.string.about), 18));
        about.addView(text(getString(R.string.about_text, BuildConfig.VERSION_NAME), 14, R.color.muted), space(10));
        addButton(about, R.string.project_link, false, view -> openLink("https://github.com/nico579/watch2notif"));
    }

    @Override protected void onActivityResult(int request, int result, Intent intent) {
        super.onActivityResult(request, result, intent);
        if (request == BATTERY) { if (selectedTab == 2) monitoringControls(); else render(); return; }
        if (request == UPDATE_PERMISSION) {
            appUpdates.feedback(getPackageManager().canRequestPackageInstalls() ? R.string.update_permission_granted : R.string.update_permission_denied);
            return;
        }
        if (request == UPDATE_INSTALL) { if (result != RESULT_OK) appUpdates.feedback(R.string.update_install_cancelled); return; }
        IntentResult scan = IntentIntegrator.parseActivityResult(request, result, intent);
        if (scan != null) {
            if (scan.getContents() != null) receiveFromPc(scan.getContents());
            return;
        }
        if (result != RESULT_OK || intent == null || intent.getData() == null) return;
        Uri uri = intent.getData();
        if (request == EXPORT) {
            final String document = exportDocument; exportDocument = null;
            WatchApp.IO.execute(() -> {
                try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                    if (output == null || document == null) throw new IllegalStateException();
                    output.write(document.getBytes(StandardCharsets.UTF_8)); runOnUiThread(() -> toast(R.string.exported));
                } catch (Exception failure) { runOnUiThread(() -> toast(R.string.file_error)); }
            });
        } else if (request == IMPORT) {
            WatchApp.IO.execute(() -> {
                try (InputStream input = getContentResolver().openInputStream(uri); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    if (input == null) throw new IllegalStateException();
                    byte[] buffer = new byte[4096]; int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (output.size() + count > 1024 * 1024) throw new IllegalArgumentException(); output.write(buffer, 0, count);
                    }
                    List<Feed> feeds = Feed.importConfig(new JSONObject(output.toString(StandardCharsets.UTF_8.name())));
                    runOnUiThread(() -> new AlertDialog.Builder(this).setTitle(R.string.import_config)
                            .setMessage(getString(R.string.import_question, feeds.size())).setNegativeButton(R.string.cancel, null)
                            .setPositiveButton(R.string.import_config, (dialog, which) -> {
                                try { store.replaceFeeds(feeds); Scheduler.sync(this); Scheduler.initialCheck(this); toast(R.string.imported); render(); }
                                catch (Exception failure) { toast(R.string.error_storage); }
                            }).show());
                } catch (Exception failure) { runOnUiThread(() -> toast(R.string.invalid_config)); }
            });
        }
    }

    private void receiveFromPc(String qr) {
        clearPairing();
        pairing = new PairingSession(this, qr);
        if (resumed) pairing.attach(this::showPairing);
    }

    private void updateCard() {
        LinearLayout updates = card(); updates.addView(heading(getString(R.string.updates), 18));
        updates.addView(text(getString(R.string.update_current_version, BuildConfig.VERSION_NAME), 13, R.color.muted), space(8));
        updateStatus = text("", 14, R.color.foreground); updates.addView(updateStatus, space(10));
        updateAction = button(R.string.update_download, true, view -> { if (appUpdates.state == UpdateSession.State.READY) installUpdate(); else appUpdates.download(); });
        updates.addView(updateAction, space(12));
        updateCheck = button(R.string.update_check, false, view -> appUpdates.check(true)); updates.addView(updateCheck, space(12));
        updateCancel = button(R.string.cancel, false, view -> appUpdates.cancel()); updates.addView(updateCancel, space(12));
        note(updates, R.string.update_note); updateControls();
    }
    private void updateChanged() {
        updateControls();
        if (selectedTab != 2 && displayedUpdateState != appUpdates.state
                && (appUpdates.state == UpdateSession.State.AVAILABLE || appUpdates.state == UpdateSession.State.READY)) render();
        displayedUpdateState = appUpdates.state;
    }
    private void updateControls() {
        if (updateStatus == null) return;
        String message;
        switch (appUpdates.state) {
            case CHECKING: message = getString(R.string.update_checking); break;
            case CURRENT: message = getString(R.string.update_current); break;
            case AVAILABLE: message = getString(R.string.update_available, appUpdates.release.version); break;
            case DOWNLOADING: message = getString(R.string.update_downloading, appUpdates.percent); break;
            case VERIFYING: message = getString(R.string.update_verifying); break;
            case READY: message = getString(R.string.update_ready, appUpdates.release.version); break;
            case FAILED: message = getString(appUpdates.failure); break;
            default: message = getString(R.string.update_idle);
        }
        if (appUpdates.feedback != 0) message += "\n" + getString(appUpdates.feedback);
        updateStatus.setText(message);
        updateAction.setText(appUpdates.state == UpdateSession.State.READY ? R.string.update_install : R.string.update_download);
        updateAction.setVisibility(appUpdates.release != null && !appUpdates.busy() ? View.VISIBLE : View.GONE);
        updateCheck.setEnabled(!appUpdates.busy() && appUpdates.state != UpdateSession.State.READY);
        updateCancel.setVisibility(appUpdates.busy() ? View.VISIBLE : View.GONE);
    }
    @SuppressWarnings("deprecation")
    private void installUpdate() {
        try {
            if (!getPackageManager().canRequestPackageInstalls()) {
                appUpdates.feedback(R.string.update_permission);
                startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())), UPDATE_PERMISSION);
                return;
            }
            appUpdates.prepareInstall(file -> {
                if (!resumed || isFinishing() || isDestroyed()) return;
                try {
                    Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".updates", file);
                    Intent installer = new Intent(Intent.ACTION_INSTALL_PACKAGE).setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).putExtra(Intent.EXTRA_RETURN_RESULT, true);
                    installer.setClipData(ClipData.newRawUri(getString(R.string.updates), uri));
                    startActivityForResult(installer, UPDATE_INSTALL);
                } catch (RuntimeException unavailable) { appUpdates.feedback(R.string.update_installer_unavailable); }
            });
        } catch (RuntimeException unavailable) { appUpdates.feedback(R.string.update_installer_unavailable); }
    }
    private void dismissSmokeDialog() {
        if (smokeDialog != null) smokeDialog.dismiss();
        smokeDialog = null; smokeSummary = null; smokeRows = null;
    }
    private void closeSmoke() { if (smoke != null) smoke.close(); smoke = null; dismissSmokeDialog(); }
    private void showSmoke() {
        if (!resumed || smoke == null || isFinishing() || isDestroyed()) return;
        if (smokeDialog == null) {
            LinearLayout report = column(); report.setPadding(dp(24), dp(12), dp(24), dp(12));
            smokeSummary = text("", 16, R.color.foreground); report.addView(smokeSummary);
            ScrollView details = new ScrollView(this); smokeRows = column(); details.addView(smokeRows);
            report.addView(details, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(300)));
            smokeDialog = new AlertDialog.Builder(this).setTitle(R.string.smoke_title).setView(report)
                    .setPositiveButton(android.R.string.ok, (dialog, which) -> closeSmoke()).setOnCancelListener(dialog -> closeSmoke()).show();
        }
        int ok = 0, failed = 0, skipped = 0;
        smokeRows.removeAllViews();
        for (AccessSmokeTest.Row row : smoke.rows) {
            String status; int shade;
            switch (row.outcome) {
                case OK: ok++; status = getString(R.string.smoke_ok); shade = R.color.success; break;
                case FAILED: failed++; status = getString(SourceException.message(row.error, row.httpCode), row.httpCode); shade = R.color.warning; break;
                case SKIPPED: skipped++; status = getString("disabled".equals(row.error) ? R.string.source_disabled : R.string.smoke_unused); shade = R.color.muted; break;
                default: status = getString(R.string.smoke_pending); shade = R.color.muted;
            }
            smokeRows.addView(text(row.label + " · " + status, 14, shade), space(12));
        }
        smokeSummary.setText(getString(smoke.running ? R.string.smoke_running : R.string.smoke_finished, ok, failed, skipped));
        smokeDialog.getButton(AlertDialog.BUTTON_POSITIVE).setText(smoke.running ? R.string.cancel : android.R.string.ok);
    }

    private void dismissPairingDialog() {
        if (pairingDialog != null) pairingDialog.dismiss();
        pairingDialog = null; pairingDialogState = null;
    }

    private void clearPairing() {
        if (pairing != null) pairing.close();
        pairing = null; dismissPairingDialog();
    }

    private void showPairing() {
        if (!resumed || pairing == null || store == null || isFinishing() || isDestroyed()) return;
        PairingSession.State state = pairing.state();
        if (pairingDialog != null && pairingDialogState == state) return;
        dismissPairingDialog();
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle(R.string.pair_title);
        if (state == PairingSession.State.RECEIVING) {
            LinearLayout progress = column(); progress.setPadding(dp(24), dp(12), dp(24), dp(12));
            progress.addView(new ProgressBar(this));
            progress.addView(text(getString(R.string.pair_receiving), 16, R.color.foreground), space(12));
            progress.addView(text(getString(R.string.pair_endpoint, pairing.endpoint), 13, R.color.muted), space(8));
            dialog.setView(progress).setCancelable(false).setNegativeButton(R.string.cancel, (view, which) -> clearPairing());
        } else if (state == PairingSession.State.RECEIVED) {
            PairingClient.Received received = pairing.received();
            dialog.setMessage(getString(R.string.pair_import_question, received.feeds.size(),
                    (received.github.isEmpty() ? 0 : 1) + (received.youtube.isEmpty() ? 0 : 1) + (received.claude.isEmpty() ? 0 : 1)))
                    .setNegativeButton(R.string.cancel, (view, which) -> clearPairing())
                    .setPositiveButton(R.string.import_config, (view, which) -> importPairing());
        } else if (state == PairingSession.State.IMPORTED) {
            dialog.setMessage(R.string.pair_imported).setPositiveButton(android.R.string.ok, (view, which) -> clearPairing());
        } else if (state == PairingSession.State.FAILED) {
            SourceException failure = pairing.failure();
            String message = "pair_http".equals(failure.code) ? getString(R.string.pair_http, failure.httpStatus)
                    : getString(PairingClient.errorMessage(failure.code));
            if (!pairing.endpoint.isEmpty()) message += "\n\n" + getString(R.string.pair_endpoint, pairing.endpoint);
            dialog.setMessage(message).setPositiveButton(android.R.string.ok, (view, which) -> clearPairing());
        } else return;
        dialog.setOnCancelListener(view -> clearPairing());
        pairingDialogState = state;
        pairingDialog = dialog.show();
    }

    private void importPairing() {
        if (pairing == null || pairing.state() != PairingSession.State.RECEIVED) return;
        PairingClient.Received received = pairing.received();
        try {
            SecretStore secrets = new SecretStore(this);
            String github = received.github.isEmpty() ? secrets.get("github") : received.github;
            String youtube = received.youtube.isEmpty() ? secrets.get("youtube") : received.youtube;
            String claude = received.claude.isEmpty() ? secrets.get("claude") : received.claude;
            store.replaceFeeds(received.feeds, secrets.encrypted(github, youtube, claude));
            Scheduler.sync(this); Scheduler.initialCheck(this);
            selectedTab = 0; render(); pairing.imported();
        } catch (Exception failure) {
            toast(R.string.credentials_failed);
            dismissPairingDialog();
            root.post(this::showPairing);
        }
    }

    private String date(long milliseconds) { return DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(new Date(milliseconds)); }
    private void toast(int message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }
    private void openLink(String address) {
        if (!Models.webLink(address)) { toast(R.string.no_link); return; }
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(address))); }
        catch (ActivityNotFoundException failure) { toast(R.string.no_browser); }
    }
}
