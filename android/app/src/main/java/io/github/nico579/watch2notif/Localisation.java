package io.github.nico579.watch2notif;

import android.content.Context;
import android.content.res.Configuration;
import android.os.LocaleList;
import java.util.Locale;

final class Localisation {
    static Context context(Context base) {
        String language;
        try { language = Store.get(base).language(); } catch (RuntimeException unreadableData) { return base; }
        if (!language.equals("fr") && !language.equals("en")) return base;
        Configuration configuration = new Configuration(base.getResources().getConfiguration());
        configuration.setLocales(new LocaleList(Locale.forLanguageTag(language)));
        return base.createConfigurationContext(configuration);
    }
}
