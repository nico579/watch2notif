package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;
import static io.github.nico579.watch2notif.ProviderSupport.*;

final class GithubSponsorsProvider implements Provider {
    private static final Metadata METADATA = new Metadata("github_sponsors", R.string.github_sponsors_label, R.string.github_sponsors_hint, 1800);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!source.matches("[A-Za-z0-9][A-Za-z0-9-]{0,38}")) throw new IllegalArgumentException("login");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String login = feed.url, token = request.requiredCredential("github", "github_token");
        String fields = "sponsorshipsAsMaintainer(first:100,includePrivate:true,orderBy:{field:CREATED_AT,direction:DESC})"
                + "{nodes{id createdAt isOneTimePayment tier{name monthlyPriceInDollars} sponsorEntity{__typename ... on User{login url name} ... on Organization{login url name}}}}";
        JSONObject variables = new JSONObject().put("login", login);
        JSONObject profile = graphql(request, "query($login:String!){user(login:$login){" + fields + "}}", variables, token, true).optJSONObject("user");
        if (profile == null) profile = graphql(request, "query($login:String!){organization(login:$login){" + fields + "}}", variables, token, true).optJSONObject("organization");
        if (profile == null) throw new SourceException("not_found");
        List<Entry> result = new ArrayList<>();
        JSONArray rows = profile.getJSONObject("sponsorshipsAsMaintainer").getJSONArray("nodes");
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i), entity = row.optJSONObject("sponsorEntity"), tier = row.optJSONObject("tier");
            String author = str(entity, "login", "?");
            String title = str(entity, "name", "");
            if (title.trim().isEmpty()) title = author.equals("?") ? request.context.getString(R.string.anonymous_sponsor) : author;
            String summary = row.optBoolean("isOneTimePayment") ? request.context.getString(R.string.one_time_donation)
                    : tier != null && !tier.isNull("monthlyPriceInDollars")
                    ? request.context.getString(R.string.monthly_donation, tier.getString("monthlyPriceInDollars")) : str(tier, "name", "");
            result.add(new Entry(row.getString("id"), title, author, str(entity, "url", ""), summary, timestamp(str(row, "createdAt", ""))));
        }
        return result;
    }
}
