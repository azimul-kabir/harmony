# Configuration

> v2.0.0 configuration guide

Harmony loads deployment defaults from `.env.local` when present, otherwise
`.env.development`. The Settings UI persists supported runtime overrides in
SQLite and applies them without rewriting the environment file. Credentials,
paths, executable locations, listener settings, and the database URL remain
deployment environment concerns.

## Navidrome

```env
NAVIDROME_URL=http://navidrome:4533
NAVIDROME_USERNAME=
NAVIDROME_PASSWORD=
NAVIDROME_DIRECT_PLAYLIST_SYNC_ENABLED=true
```

The URL must be reachable from the Harmony container. Credentials stay
server-side and use the Subsonic token flow. Direct sync resolves stable song
IDs, replaces playlists in source order, verifies the result, and falls back to
M3U import when direct reconciliation is unsafe. Search limits, duration
tolerance, reimport debounce/poll intervals, and scan timeout can be adjusted
under **Settings → Navidrome**.

## YouTube Music

```env
YOUTUBE_MUSIC_ENABLED=true
YT_DLP_PATH=yt-dlp
DEFAULT_DOWNLOAD_SOURCE=spotify
YOUTUBE_MUSIC_TIMEOUT_SECONDS=300
```

This provider accepts public YouTube Music and explicit YouTube URLs. It uses
yt-dlp without cookies or authenticated catalogue scraping and remains subject
to provider availability and restrictions. Timeout, playlist/search/queue
limits, enabled state, and default source are available under Settings.

## MusicBrainz and artwork

Set `MUSICBRAINZ_*` values to tune timeout, retry, request rate, cache TTL, and
concurrency. Keep a descriptive `MUSICBRAINZ_USER_AGENT`. `METADATA_DISCOVERY_*`
values bound chunk and batch sizes. `COVER_ART_ARCHIVE_*` values control remote
artwork fetch timeout and response size.

The defaults are conservative for public provider infrastructure. Metadata
discovery is review-first; changing provider settings never authorizes
automatic canonical changes or file-tag writes.

## Optional Spotify genre enrichment

`SPOTIFY_GENRE_ENRICHMENT_ENABLED` is `false` by default. Harmony therefore does not create a Spotify client, authenticate, request a token, or call a Spotify API endpoint merely to download, tag, resolve metadata, or index the library. MusicBrainz enrichment and genres embedded in audio files continue to work without Spotify.

To use Spotify artist metadata as an additional, best-effort genre source, set the flag to `true` and configure both credentials:

```env
SPOTIFY_GENRE_ENRICHMENT_ENABLED=false
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
```

Spotify genres can be empty or unavailable. A missing credential or provider failure is non-fatal and never blocks a download. Existing genres and their provenance are retained when the feature is disabled. The precedence is: user-provided genre, MusicBrainz genre, enabled Spotify genre, embedded genre, then empty.

## Source schedules and auto-playlists

Source auto-sync is configured per Source in the Sources UI, not through an
environment variable. v2.0.0 offers hourly, 6-hour, 12-hour, daily, and weekly
intervals. Enabling auto-sync also enables the Source.

Recently Added and Recently Downloaded auto-playlists are configured from the
Playlists page. Each stores its enabled state and a 1–500-song limit; 50 is the
default.

## Runtime settings

The UI validates bounded settings for Downloads, Spotify enrichment,
MusicBrainz/Cover Art Archive, Navidrome reconciliation, and the Library
watcher. Invalid updates return HTTP 422 and leave the previous value in place.
General date/time, theme, audio quality, worker, retry, playlist, and export
preferences are also persisted.
