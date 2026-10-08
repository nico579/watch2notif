package io.github.nico579.watch2notif;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import static io.github.nico579.watch2notif.Models.*;

final class Notifications {
    static final String ITEMS = "new-items", MONITOR = "monitoring";
    static final int SERVICE_ID = 1;

    static void channels(Context context) {
        Context translated = Localisation.context(context);
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(ITEMS, translated.getString(R.string.notification_channel), NotificationManager.IMPORTANCE_DEFAULT));
        manager.createNotificationChannel(new NotificationChannel(MONITOR, translated.getString(R.string.service_channel), NotificationManager.IMPORTANCE_LOW));
    }

    static boolean allowed(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        NotificationChannel channel = manager.getNotificationChannel(ITEMS);
        return manager.areNotificationsEnabled() && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE)
                && (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED);
    }

    static PendingIntent appIntent(Context context) {
        return PendingIntent.getActivity(context, 0, new Intent(context, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static Notification monitoring(Context context) {
        Context translated = Localisation.context(context);
        PendingIntent stop = PendingIntent.getService(context, 0, new Intent(context, LivePollService.class).setAction(LivePollService.STOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(context, MONITOR).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(translated.getString(R.string.service_title)).setContentText(translated.getString(R.string.service_body))
                .setContentIntent(appIntent(context)).setOngoing(true).setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, translated.getString(R.string.service_stop), stop).build()).build();
    }

    static boolean send(Context context, Feed feed, Entry entry) {
        if (!allowed(context)) return false;
        try {
            PendingIntent content = Models.webLink(entry.link) ? PendingIntent.getActivity(context, 0,
                    new Intent(Intent.ACTION_VIEW, Uri.parse(entry.link)), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE) : appIntent(context);
            String title = entry.title.trim().isEmpty() ? context.getString(R.string.untitled) : entry.title;
            String body = compact(entry.summary, 300);
            if (!entry.author.trim().isEmpty()) body = entry.author + " · " + body;
            Notification notification = new Notification.Builder(context, ITEMS).setSmallIcon(R.drawable.ic_notification)
                    .setContentTitle("[" + feed.label + "] " + title).setContentText(body).setStyle(new Notification.BigTextStyle().bigText(body))
                    .setContentIntent(content).setAutoCancel(true).setOnlyAlertOnce(true)
                    .setGroup("watch2notif.items").setVisibility(Notification.VISIBILITY_PRIVATE).build();
            context.getSystemService(NotificationManager.class).notify(hash(feed.key + "\n" + entry.id), 2, notification);
            return true;
        } catch (SecurityException denied) { return false; }
    }
}
