package io.github.nico579.watch2notif;

/** Only fixed error codes are persisted: server messages can contain tokens or private feed URLs. */
final class SourceException extends Exception {
    final String code;
    final int httpStatus;
    SourceException(String code) { this(code, 0); }
    SourceException(String code, int status) { super(code); this.code = code; this.httpStatus = status; }

    static int message(String code, int status) {
        if ("http".equals(code) && status == 401) return R.string.error_unauthorized;
        if ("http".equals(code) && status == 403) return R.string.error_forbidden;
        if ("http".equals(code) && status == 429) return R.string.error_rate_limit;
        return message(code);
    }

    static int message(String code) {
        switch (code) {
            case "http": return R.string.error_http;
            case "parse": return R.string.error_parse;
            case "github_token": return R.string.error_github_token;
            case "youtube_key": return R.string.error_youtube_key;
            case "claude_key": return R.string.ai_key_missing;
            case "timeout": return R.string.smoke_timeout;
            case "graphql": return R.string.error_graphql;
            case "not_found": return R.string.error_not_found;
            case "storage": return R.string.error_storage;
            case "redirect": return R.string.error_redirect;
            default: return R.string.error_network;
        }
    }
}
