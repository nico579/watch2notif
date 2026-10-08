package io.github.nico579.watch2notif;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

final class Network {
    interface Transport {
        byte[] request(String address, String token, String body, boolean api) throws SourceException;
    }

    static final class HttpTransport implements Transport {
        @Override public byte[] request(String address, String token, String body, boolean api) throws SourceException {
            if (!Models.webLink(address)) throw new SourceException("parse");
            try {
                URI current = URI.create(address);
                for (int redirects = 0; redirects <= 5; redirects++) {
                    if (Thread.currentThread().isInterrupted()) throw new SourceException("network");
                    HttpURLConnection connection = (HttpURLConnection) new URL(current.toString()).openConnection();
                    connection.setConnectTimeout(15000); connection.setReadTimeout(15000);
                    connection.setInstanceFollowRedirects(false);
                    connection.setRequestProperty("User-Agent", "watch2notif-android/" + BuildConfig.VERSION_NAME);
                    connection.setRequestProperty("Accept", api ? "application/json" : "application/rss+xml, application/atom+xml, application/xml, text/xml, */*");
                    if ("api.github.com".equalsIgnoreCase(current.getHost()) && api) {
                        connection.setRequestProperty("Accept", "application/vnd.github+json");
                        connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
                        if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
                    }
                    if ("api.anthropic.com".equalsIgnoreCase(current.getHost()) && api) {
                        connection.setRequestProperty("x-api-key", token);
                        connection.setRequestProperty("anthropic-version", "2023-06-01");
                    }
                    try {
                        if (body != null) {
                            connection.setRequestMethod("POST"); connection.setDoOutput(true);
                            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                            byte[] payload = body.getBytes(StandardCharsets.UTF_8);
                            connection.setFixedLengthStreamingMode(payload.length);
                            try (java.io.OutputStream output = connection.getOutputStream()) { output.write(payload); }
                        }
                        int status = connection.getResponseCode();
                        if (status == 301 || status == 302 || status == 303 || status == 307 || status == 308) {
                            // Never forward credentials or a GraphQL POST to a redirected endpoint.
                            String target = connection.getHeaderField("Location");
                            if (api || body != null || target == null || redirects == 5) throw new SourceException("redirect");
                            URI next = current.resolve(target);
                            if (!Models.webLink(next.toString()) || ("https".equalsIgnoreCase(current.getScheme())
                                    && !"https".equalsIgnoreCase(next.getScheme()))) throw new SourceException("redirect");
                            current = next; continue;
                        }
                        if (status < 200 || status >= 300) throw new SourceException("http", status);
                        if (connection.getContentLengthLong() > 8 * 1024 * 1024) throw new SourceException("parse");
                        long deadline = System.nanoTime() + 30000000000L;
                        try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                            byte[] buffer = new byte[8192]; int count;
                            while ((count = input.read(buffer)) != -1) {
                                if (Thread.currentThread().isInterrupted() || System.nanoTime() > deadline) throw new SourceException("network");
                                if (output.size() + count > 8 * 1024 * 1024) throw new SourceException("parse");
                                output.write(buffer, 0, count);
                            }
                            return output.toByteArray();
                        }
                    } finally { connection.disconnect(); }
                }
                throw new SourceException("redirect");
            } catch (SourceException failure) { throw failure; }
            catch (Exception ignored) { throw new SourceException("network"); }
        }
    }
}
