package io.github.nico579.watch2notif;

import android.text.Html;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.nio.charset.StandardCharsets;

final class ProviderSupport {
    private ProviderSupport() { }

    static String plain(String value) {
        return Html.fromHtml(value, Html.FROM_HTML_MODE_LEGACY).toString().trim();
    }

    static String resolve(String base, String value) {
        try { return URI.create(base).resolve(value).toString(); } catch (Exception ignored) { return ""; }
    }

    static JSONObject graphql(Provider.Request request, String query, JSONObject variables, String token, boolean nullable) throws Exception {
        String payload = new JSONObject().put("query", query).put("variables", variables).toString();
        JSONObject response = new JSONObject(new String(request.transport.request("https://api.github.com/graphql", token, payload, true), StandardCharsets.UTF_8));
        JSONArray errors = response.optJSONArray("errors");
        if (errors != null && errors.length() > 0) {
            boolean notFoundOnly = nullable;
            for (int i = 0; i < errors.length(); i++) notFoundOnly &= "NOT_FOUND".equals(errors.getJSONObject(i).optString("type"));
            if (!notFoundOnly) throw new SourceException("graphql");
        }
        JSONObject data = response.optJSONObject("data");
        if (data == null) throw new SourceException("graphql");
        return data;
    }
}
