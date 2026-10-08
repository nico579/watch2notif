package io.github.nico579.watch2notif;

import android.content.Context;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

/** Generic dispatch facade; source-specific behavior lives in registered providers. */
final class Providers {
    private final Context context;
    private final Network.Transport transport;
    private final ProviderRegistry registry;

    Providers(Context context, Network.Transport transport) { this(context, transport, ProviderRegistry.BUILTINS); }
    Providers(Context context, Network.Transport transport, ProviderRegistry registry) {
        this.context = context; this.transport = transport; this.registry = registry;
    }

    List<Entry> fetch(Feed feed, Provider.Credentials credentials) throws SourceException {
        try {
            Provider provider = registry.require(feed.kind);
            provider.validateSource(feed.url);
            return provider.fetch(feed, new Provider.Request(context, transport, credentials));
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("parse"); }
    }

    // Compatibility helper for callers supplying already decrypted credentials.
    List<Entry> fetch(Feed feed, String githubToken, String youtubeKey) throws SourceException {
        return fetch(feed, name -> "github".equals(name) ? githubToken : "youtube".equals(name) ? youtubeKey : "");
    }

    List<Entry> rss(byte[] document, String sourceUrl) throws SourceException {
        return RssProvider.parse(document, sourceUrl);
    }
}
