***English** | [Français](README.fr.md)*

# watch2notif

Small desktop tool that watches sources (RSS/Atom feeds, GitHub issues,
YouTube comments...) and fires a native, clickable notification
whenever something new shows up. Cross-platform (Windows/Linux/Mac).

Started as a Reddit inbox watcher (via Reddit's private RSS feeds,
reddit.com/prefs/feeds), then generalized: any RSS/Atom feed works, plus
GitHub issues polling for public repos (no auth needed), GitHub
discussion replies, and YouTube video comments. New source types are
added as a `providers/` module, nothing else to touch.

## Screenshots

A [native Android app](android/README.md) supports notifications, history,
optional Claude filtering and encrypted configuration/API-key transfer from
the desktop over the LAN. Click **Send to phone** on the PC and scan its
single-use, two-minute QR in Android Settings. Signed Android APKs and desktop
bundles are built and tested on GitHub Actions and published together in
[GitHub releases](https://github.com/nico579/watch2notif/releases).
Ordinary JSON source import/export is also available.

![Settings panel](screenshots/settings_en.png)
![Tray menu](screenshots/systray_en.png)
![Notification history](screenshots/history_en.png)

## How it works

- `notifier.py`: background loop, polls the sources enabled in
  `config.json`, each on its own interval, fires a desktop notification
  (clickable, opens the source's link) for each new entry. Per-source
  "already seen" state kept in `state/`. `config.json`, `state/` and the
  notification history live in the OS's standard per-user data directory
  (`%APPDATA%` on Windows, XDG data dir on Linux, Application Support on
  Mac, via `platformdirs`, see `data_paths.py`), never next to the
  executable: a reinstall or rebuild must never wipe them. Also the single
  entry point of
  the built binary: a system tray icon (`pystray`, through
  [nico579-commons](https://github.com/nico579/nico579-commons)) with the
  same menu as its three sibling apps: Open (the settings/history page, in
  the default browser), "Update to x.y" when a newer version is out,
  Restart, Stop, and "Create a Desktop shortcut". Pausing, the history and
  the GitHub help link live in the page. It checks the GitHub releases
  page every 6h and adds that menu entry + one desktop notification when
  a newer version is out. In
  a packaged app, the settings page offers to install it, verifies the
  published asset's size and SHA-256, then replaces the bundle after
  shutdown and restarts it while preserving settings and notification
  history (`update_check.py`, `self_update.py`). A source checkout is
  never modified automatically.
- `providers/`: one module per source type (`rss.py`, `github_issues.py`,
  `github_discussion.py`, `youtube_comments.py`), each exposing
  `fetch_entries(source) -> list[Entry]`. Adding a new source type means
  adding a module here, nothing else changes.
- `gui/` + `nico579_commons.serveweb`: settings/history page (add/remove sources,
  pick their type, set per-source polling interval, toggle autostart,
  browse the last 200 notifications actually sent, double-click a row to
  reopen its link) served on local HTTP (stdlib `http.server`, no
  framework) and opened in the system's default browser — same
  architecture as the sibling projects, lidar2map and blink2video.
  Bilingual FR/EN, toggle top-right. Reachable from the tray's "Open"
  item, or with `notifier.py --settings`.
- `notify_backend.py`: notification backend per OS — `win11toast`
  (Windows, modern WinRT toast, correct app name, clickable), `pync`
  (Mac, via terminal-notifier, clickable), `plyer` (Linux, not clickable
  yet).
- `autostart_manager.py`: enables/disables autostart depending on the OS
  (shortcut in the Startup folder on Windows, systemd user service on
  Linux, launchd on Mac). Detects PyInstaller's frozen mode to point at
  the built binary instead of the Python script.

## Installation

### From source

```bash
pip install -r requirements.txt
python notifier.py   # first run opens the settings page in your browser
```

### Standalone binary

Each release ships pre-built bundles (Windows/Linux/Mac) on the
[Releases](../../releases) page, no Python required: a single executable,
`watch2notif`. Run it to start watching; open the settings/history page
from its tray icon ("Open") or with `watch2notif --settings`.

When a compatible update is published, the settings page shows a banner
before downloading anything. "Download and install", or "Update to x.y"
in the tray menu, prepares and
validates the whole new bundle first; watch2notif closes only when the
external updater is ready, then restarts on the new version. If
preparation, replacement, or restart fails, the current installation is
kept or restored. Unsupported platforms fall back to the release page.

## Builds and tests on GitHub

GitHub Actions builds Windows, Linux and macOS bundles plus the Android APK
and AAB on each `v*` tag. Publication requires Python tests on all three OSes,
Android/Robolectric tests, Android Lint and executable smoke checks to pass.
No locally compiled binary is uploaded to releases.

Pull requests and changes to `master` also run CI. See
[.github/workflows/ci.yml](.github/workflows/ci.yml),
[android.yml](.github/workflows/android.yml) and
[release.yml](.github/workflows/release.yml).

## Sources

### RSS/Atom (any feed)

Any valid RSS/Atom URL works. For Reddit specifically: on
`https://www.reddit.com/prefs/feeds/`, each feed (inbox, front page,
saved, upvoted...) has an RSS/JSON link with a private token in the URL.
This token doesn't expire unless you change your account password.
Don't share these URLs: they grant read access to the associated private
content.

Reddit's classic Data API (OAuth, what `praw` uses) now requires a
moderation use case to register a new application. These private RSS
feeds remain an official feature, without that restriction, and are
enough for personal read-only use.

Forums built on SMF (Simple Machines Forum, a common PHP forum engine)
expose a native per-topic RSS feed, no plugin needed: append
`?action=.xml;type=rss2;topic=<id>.0` to the forum's `index.php` URL,
where `<id>` is the numeric topic ID found in the topic's own URL
(`index.php?topic=<id>.<offset>`). It only returns posts in that thread,
so it works as a "notify me on new replies to my post" watcher.

### GitHub issues (public repos)

Enter `owner/repo` as the source. Uses GitHub's public REST API, no
authentication needed for public repos. Rate-limited to 60 requests/hour
per IP without a token, 5000/hour with one (set the `GITHUB_TOKEN`
environment variable). If the `gh` CLI is already installed and logged
in, `gh auth token` prints one; otherwise create one manually on
GitHub.com: avatar menu -> Settings -> Developer settings -> Personal
access tokens -> Tokens (classic) -> Generate new token (classic). No
scope needs to be checked for read-only access to public repos, the
token only needs to exist to authenticate the request and lift the
per-IP limit. Prefer a longer per-source interval for this type (a few
minutes) to stay under the unauthenticated limit.

### GitHub discussion replies

Enter `owner/repo#number` as the source (the number after `/discussions/`
in the URL). Watches one Discussion thread and reports new top-level
comments and replies. Unlike GitHub issues, Discussions have no REST
endpoint at all: this goes through GitHub's GraphQL API instead, which
refuses anonymous requests even on a public repo. The `GITHUB_TOKEN`
environment variable is therefore required, not just a rate-limit
booster (same variable as GitHub issues, see above for how to obtain
one).

### GitHub Sponsors

Enter your GitHub login (or an organization's) as the source. GitHub sends
no notification of its own when someone new sponsors you ([confirmed
here](https://github.com/orgs/community/discussions/41675)): checking the
Sponsors dashboard by hand is otherwise the only way to know. Goes through
the GraphQL API like GitHub discussion replies, so `GITHUB_TOKEN` is
required there too, but with the extra `read:user` scope on top of the
usual ones: that scope is what exposes a stable ID for a sponsor who chose
to stay anonymous (their profile is hidden, but the sponsorship itself
still gets a distinct ID, so a second anonymous sponsor is never mistaken
for the first). A rare event compared to a discussion reply, so the
default interval is longer.

### YouTube comments

Enter a video URL (any common form) or a bare video ID as the source.
Watches one video and reports new top-level comments and their visible
replies. YouTube exposes an Atom feed for a channel's new uploads, but
none for comments on a video, so this goes through the YouTube Data API
v3 instead. Requires a free API key: Google Cloud Console -> APIs &
Services -> enable "YouTube Data API v3" -> Credentials -> Create API
key, then set the `YOUTUBE_API_KEY` environment variable. Quota cost is
2 units per poll (10000/day free allowance), so the default interval is
a courtesy, not a quota necessity.

## AI filter (optional)

Some sources are too broad to be useful as they are. A Reddit search for
"local storage" on a camera subreddit brings up the people who could use
your tool, but also billing complaints and pictures of new cameras. Words
alone cannot tell them apart; reading the message can.

Each source has an **AI filter** button. It opens a text box where you
describe, in plain words, which entries deserve a notification, for
example: "Questions from people who want to keep or download their Blink
clips without a subscription. Not billing complaints, not motion detection
problems." Before notifying a new entry, watch2notif sends its title and
text to Claude Haiku with your instructions, and only notifies the ones it
judges relevant, with a one-line reason at the start of the notification.
The others are remembered as seen and never sent again. An empty box means
no filtering.

It needs an Anthropic API key in the `ANTHROPIC_API_KEY` environment
variable (console.anthropic.com). The API is billed per use, separately
from any Claude subscription; sorting a few dozen messages a month with
Haiku costs a few cents. If the key is missing or the API cannot answer,
watch2notif notifies anyway and says so in the notification: an entry is
never dropped silently.

## Adding a source type

A provider is a module in `providers/` exposing two things:

- `LABEL`: display name shown in the settings panel's source-type list.
- `fetch_entries(source) -> list`: takes the source string the user
  entered (a URL, `owner/repo`...) and returns the current list of
  entries. Each entry needs `.id` and `.get(key, default)`, the shape
  `notifier.py` relies on to detect new entries and pull `title`,
  `author`, `link`, `summary`.

`SOURCE_HINT` is optional: placeholder text shown in the settings panel
next to the source input field.

If the underlying data already comes as objects with `.id`/`.get()`
(like feedparser entries in `rss.py`), return them directly. Otherwise,
wrap each item in `providers.base.Entry(id, title, author, link,
summary)`, as `github_issues.py` does for GitHub's JSON API.

Then register the module in `providers/__init__.py`'s `PROVIDERS` dict
(key = internal kind, value = the module). Nothing else changes:
`notifier.py` and the settings page (`gui/`) pick up any registered
provider through `PROVIDERS`, with no per-provider branching.

## Existing alternatives

General-purpose RSS readers (RSS Guard, QuiteRSS...) already do feed
polling with desktop notifications, but don't cover non-RSS sources like
GitHub's issues API. `watch2notif` stays minimal (no article reader) and
bundles autostart, clickable notifications, and a small provider system
to add new source types.

## License

GPLv3, see `LICENSE`.
