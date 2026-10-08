package io.github.nico579.watch2notif;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Add a provider here; the editor, validation and poller use this same registry. */
final class ProviderRegistry {
    static final ProviderRegistry BUILTINS = new ProviderRegistry(new RssProvider(), new GithubIssuesProvider(),
            new GithubDiscussionProvider(), new GithubSponsorsProvider(), new YoutubeCommentsProvider());
    private final Map<String, Provider> byKind;
    private final List<Provider> providers;

    ProviderRegistry(Provider... registered) {
        Map<String, Provider> index = new LinkedHashMap<>();
        for (Provider provider : registered) {
            Provider.Metadata metadata = provider.metadata();
            if (metadata.kind == null || metadata.kind.trim().isEmpty() || metadata.label == 0 || metadata.hint == 0
                    || metadata.defaultInterval < 5 || metadata.defaultInterval > 604800
                    || index.put(metadata.kind, provider) != null) throw new IllegalArgumentException("provider metadata");
        }
        if (index.isEmpty()) throw new IllegalArgumentException("empty provider registry");
        byKind = Collections.unmodifiableMap(index);
        providers = Collections.unmodifiableList(new ArrayList<>(index.values()));
    }

    List<Provider> all() { return providers; }

    Provider require(String kind) {
        Provider provider = byKind.get(kind);
        if (provider == null) throw new IllegalArgumentException("kind");
        return provider;
    }

    int indexOf(String kind) {
        for (int i = 0; i < providers.size(); i++) if (providers.get(i).metadata().kind.equals(kind)) return i;
        return -1;
    }

    String[] kinds() {
        String[] result = new String[providers.size()];
        for (int i = 0; i < result.length; i++) result[i] = providers.get(i).metadata().kind;
        return result;
    }

    int[] labels() {
        int[] result = new int[providers.size()];
        for (int i = 0; i < result.length; i++) result[i] = providers.get(i).metadata().label;
        return result;
    }

    int[] hints() {
        int[] result = new int[providers.size()];
        for (int i = 0; i < result.length; i++) result[i] = providers.get(i).metadata().hint;
        return result;
    }
}
