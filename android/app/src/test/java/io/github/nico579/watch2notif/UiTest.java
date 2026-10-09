package io.github.nico579.watch2notif;

import android.app.Application;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.provider.Settings;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.TextView;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.shadows.ShadowAlertDialog;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class, qualifiers = "fr-w411dp-h891dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class UiTest {
    @Before public void reset() throws Exception {
        Field singleton = Store.class.getDeclaredField("instance"); singleton.setAccessible(true); singleton.set(null, null);
        File saved = new File(RuntimeEnvironment.getApplication().getFilesDir(), "watch2notif.json");
        if (saved.exists()) assertTrue(saved.delete());
        Notifications.channels(RuntimeEnvironment.getApplication());
        RuntimeEnvironment.getApplication().getSharedPreferences("monitoring", Context.MODE_PRIVATE).edit().clear().commit();
        LivePollService.running = false;
        Store.get(RuntimeEnvironment.getApplication()).language("fr");
    }

    private View find(View view, String label) {
        if (view instanceof TextView && label.contentEquals(((TextView)view).getText())) return view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            View found = find(((ViewGroup)view).getChildAt(i), label); if (found != null) return found;
        }
        return null;
    }

    private void screenshot(MainActivity activity, String name) throws Exception {
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        View view = activity.getWindow().getDecorView(); int width = 822, height = 1782;
        view.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY));
        view.layout(0, 0, width, height); Bitmap image = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888); view.draw(new Canvas(image));
        File output = new File(System.getProperty("watch2notif.qa"), name + ".png"); assertTrue(output.getParentFile().isDirectory() || output.getParentFile().mkdirs());
        try (FileOutputStream stream = new FileOutputStream(output)) { assertTrue(image.compress(Bitmap.CompressFormat.PNG, 100, stream)); }
        image.recycle();
    }

    @Test public void sourcesSettingsAndSourceDialogAreUsableInFrench() throws Exception {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity activity = controller.get(); View root = activity.getWindow().getDecorView();
            assertNotNull(find(root, "Ajouter une source")); screenshot(activity, "android-sources-fr");
            find(root, "Ajouter une source").performClick(); AlertDialog editor = ShadowAlertDialog.getLatestAlertDialog();
            assertTrue(editor.isShowing()); assertNotNull(find(editor.getWindow().getDecorView(), "Filtre IA (facultatif)"));
            editor.getButton(AlertDialog.BUTTON_NEGATIVE).performClick();
            find(activity.getWindow().getDecorView(), "Réglages").performClick();
            assertNotNull(find(activity.getWindow().getDecorView(), "Clé API Claude (Anthropic)"));
            assertNotNull(find(activity.getWindow().getDecorView(), "Scanner le QR du PC")); screenshot(activity, "android-settings-fr");
            assertNotNull(find(activity.getWindow().getDecorView(), "Rechercher une mise à jour"));
            assertNotNull(find(activity.getWindow().getDecorView(), "Tester les accès"));
            assertNotNull(find(activity.getWindow().getDecorView(), "Surveillance en arrière-plan"));
            assertNotNull(find(activity.getWindow().getDecorView(), "Autoriser la surveillance en arrière-plan"));
            find(activity.getWindow().getDecorView(), "Historique").performClick();
            assertNotNull(find(activity.getWindow().getDecorView(), "Vous êtes à jour")); screenshot(activity, "android-history-fr");
        }
    }

    @Test public void batteryPermissionBelongsToAndroidAndIsNotSilentlyGranted() throws Exception {
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            MainActivity activity = controller.get();
            find(activity.getWindow().getDecorView(), "Réglages").performClick();
            assertFalse(MonitoringState.batteryUnrestricted(activity));
            find(activity.getWindow().getDecorView(), "Autoriser la surveillance en arrière-plan").performClick();
            Intent request = Shadows.shadowOf(activity).getNextStartedActivity();
            assertEquals(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, request.getAction());
            assertEquals("package:" + activity.getPackageName(), request.getDataString());
            assertFalse(MonitoringState.batteryUnrestricted(activity));
        }
    }
}
