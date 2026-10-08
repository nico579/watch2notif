package io.github.nico579.watch2notif;

import android.content.Context;
import java.io.IOException;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

/** One source kind owns its metadata, validation, credentials and fetching. */
interface Provider {
    Metadata metadata();
    void validateSource(String source);
    List<Entry> fetch(Feed feed, Request request) throws Exception;

    interface Credentials { String get(String name) throws Exception; }

    final class Metadata {
        final String kind;
        final int label, hint, defaultInterval;
        Metadata(String kind, int label, int hint, int defaultInterval) {
            this.kind = kind; this.label = label; this.hint = hint; this.defaultInterval = defaultInterval;
        }
    }

    final class Request {
        final Context context;
        final Network.Transport transport;
        private final Credentials credentials;
        Request(Context context, Network.Transport transport, Credentials credentials) {
            this.context = context; this.transport = transport; this.credentials = credentials;
        }

        String credential(String name) throws SourceException {
            try {
                String value = credentials.get(name);
                return value == null ? "" : value;
            } catch (SourceException failure) { throw failure; }
            catch (Exception failure) { throw new SourceException(failure instanceof IOException ? "storage" : "network"); }
        }

        String requiredCredential(String name, String error) throws SourceException {
            String value = credential(name);
            if (value.trim().isEmpty()) throw new SourceException(error);
            return value;
        }
    }
}
