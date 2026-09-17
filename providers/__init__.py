"""Registry of providers (notification sources). Each provider is a module
that exposes fetch_entries(source) -> list[Entry] and a LABEL for display
in settings.py. Adding a source = adding a module here and a line in
PROVIDERS, nothing else to touch in notifier.py or settings.py (same
spirit as the lidar providers in lidar2map)."""
from . import github_discussion, github_issues, github_sponsors, rss, youtube_comments

PROVIDERS = {
    "rss": rss,
    "github_issues": github_issues,
    "github_discussion": github_discussion,
    "github_sponsors": github_sponsors,
    "youtube_comments": youtube_comments,
}

DEFAULT_KIND = "rss"
