# Configuration

> v2.1.0 configuration guide

Harmony loads deployment defaults from the single `.env` file used by Docker
Compose. The Settings UI persists supported runtime overrides in
SQLite and applies them without rewriting the environment file. Credentials,
paths, executable locations, listener settings, and the database URL remain
deployment environment concerns.

## Web login

Authentication is enabled by default and protects the Web UI, API, interactive
API documentation, and event streams with a signed, HTTP-only session cookie.
Static assets plus liveness and readiness probes remain public so the login
page and container health checks continue to work.

Copy `.env.example` to `.env`, set a long, unique password, and never commit
`.env`:

```env
WEB_AUTH_ENABLED=true
WEB_AUTH_USERNAME=admin
WEB_AUTH_PASSWORD=replace-with-a-long-unique-password
WEB_AUTH_SESSION_HOURS=12
WEB_AUTH_SECURE_COOKIE=false
```

Harmony derives the session-signing key from the password, so there is no
second secret to maintain and changing the password invalidates existing
sessions. An enabled configuration with an empty password fails closed:
protected routes remain inaccessible and the login page reports that
authentication is not configured. Set `WEB_AUTH_SECURE_COOKIE=true` when the
browser reaches Harmony through HTTPS. For access outside a trusted private
network, place Harmony behind an HTTPS reverse proxy; the login portal does not
provide TLS or brute-force protection by itself. `WEB_AUTH_ENABLED=false` is
meant only for isolated development.

## Docker Compose and paths

`docker-compose.yml` and `.env` are the complete deployment configuration; no
override or second environment file is required. The `MUSIC_HOST_PATH` and
`DOWNLOAD_HOST_PATH` values are host paths, while `MUSIC_PATH`,
`DOWNLOAD_PATH`, and related values remain container paths. Compose retains the
Synology `1026:100` user mapping and joins the existing external `harmony-net`
network:

```env
MUSIC_HOST_PATH=/volume1/music/library
DOWNLOAD_HOST_PATH=/volume1/music/incoming
```

## Navidrome

```env
NAVIDROME_URL=http://navidrome:4533
NAVIDROME_USERNAME=
NAVIDROME_PASSWORD=
```

The URL must be reachable from the Harmony container. Credentials stay
server-side and use the Subsonic token flow. Harmony exports M3U playlists and
asks Navidrome to scan after completed playlist downloads. Reimport debounce,
poll interval, and scan timeout can be adjusted under **Settings → Navidrome**.

## YouTube Music

```env
YOUTUBE_MUSIC_ENABLED=true
YT_DLP_PATH=yt-dlp
YT_DLP_COOKIE_FILE=
YOUTUBE_MUSIC_TIMEOUT_SECONDS=300
```

This provider accepts public YouTube Music and explicit YouTube URLs. It uses
yt-dlp and remains subject to provider availability and restrictions. An
optional read-only cookies file can authenticate audio requests when YouTube
challenges the server IP; authenticated catalogue scraping and private playlist
synchronization remain unsupported. Timeout, playlist/search/queue limits,
enabled state, and default source are available under Settings.

The Sources page accepts public `music.youtube.com/playlist?list=...` URLs in
addition to Spotify playlists. Extra YouTube Music query parameters are removed
when the Source is saved. During synchronization Harmony uses flat playlist
metadata extraction, skips unavailable/private/deleted entries, and creates
download jobs for missing tracks with `youtube_music` source identity. Enable
the YouTube Music download source before syncing when missing tracks should be
acquired. Cookies and private playlists are not supported.

Existing Spotify Sources are migrated in place. Their legacy Spotify columns
remain compatibility mirrors, while `provider`, `external_id`, and `source_url`
are the authoritative durable identity. Source uniqueness is scoped by provider.

### Troubleshooting YouTube download failures

Playlist synchronization and audio acquisition are separate operations. A sync
can finish successfully and export an M3U with (for example) 49 of 50 tracks
available while the queued download for the missing track fails later.

Both Spotify-backed downloads and manual YouTube fallbacks ultimately obtain
audio through yt-dlp. Repeated `AudioProviderError: YT-DLP download error`
messages followed by `HTTP Error 403: Forbidden` from a manual fallback
therefore point to the shared YouTube delivery path, not Spotify metadata,
playlist synchronization, Navidrome reconciliation, or Harmony's health check.
Common causes are an outdated cached container image, a YouTube extractor
change, or YouTube refusing media delivery to the container's public IP. A
successful metadata lookup does not prove that the media URL itself is
downloadable.

Check the exact versions and reproduce the request from inside the running
container:

```sh
docker compose exec harmony yt-dlp --version
docker compose exec harmony deno --version
docker compose exec harmony yt-dlp -v -f bestaudio --no-playlist \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Pass the raw watch URL as shown. Do not paste Markdown link syntax such as
`[https://...](https://...)` into the shell.

Rebuild without the dependency layer cache before retrying so the image
contains the current yt-dlp package:

```sh
docker compose build --pull --no-cache harmony
docker compose up -d harmony
```

If a current, verbose yt-dlp request still returns HTTP 403 for multiple public
videos, inspect the lines immediately before it. `HTTP Error 429: Too Many
Requests` followed by `Sign in to confirm you're not a bot` confirms that
YouTube has challenged the container's public IP; changing the video alone will
usually not help.

Harmony can pass a Netscape-format cookies file to both SpotDL and direct
YouTube fallback downloads. Export a fresh `cookies.txt` from a dedicated
YouTube account, stop using that account in the browser session from which it
was exported, store the file outside the repository with owner-only
permissions, and mount it read-only:

```yaml
services:
  harmony:
    volumes:
      - /volume1/docker/secrets/youtube-cookies.txt:/run/secrets/youtube-cookies.txt:ro
```

Then configure the path **inside** the container and recreate it:

```env
YT_DLP_COOKIE_FILE=/run/secrets/youtube-cookies.txt
```

```sh
chmod 600 /volume1/docker/secrets/youtube-cookies.txt
docker compose up -d --force-recreate harmony
docker compose exec harmony yt-dlp --cookies /run/secrets/youtube-cookies.txt \
  -v -f bestaudio --no-playlist 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Cookies are credentials: never paste them into logs, commit them, or expose the
mount through a shared directory. YouTube may invalidate them, and using them
can affect the associated account. If cookies are not acceptable, test from a
different public network/IP. Choose a different public video when only one
video is affected.

The manual fallback endpoint returns HTTP 422 before queueing when the submitted
value is not a specific supported YouTube or YouTube Music **track** URL. HTTP
201 means only that the fallback was validated and queued; the subsequent
download can still fail if YouTube refuses the audio request.

## Large Spotify playlists

Spotify playlist downloads first run SpotDL's metadata-only `save` operation.
Harmony shows this as a distinct Source sync stage and does not create download
jobs until the complete ordered track list is available. The metadata timeout
defaults to 3600 seconds and can be changed under Settings → Downloads or with:

```env
SPOTIFY_PLAYLIST_METADATA_TIMEOUT_SECONDS=3600
```

The accepted range is 300–14400 seconds. A timeout or missing SpotDL executable
is recorded as an actionable Source task failure. In Docker, executable settings
should normally be `SPOTDL_PATH=spotdl` and `YT_DLP_PATH=yt-dlp`; do not use host
virtual-environment paths inside the container.

## Exact Spotify track acquisition

Spotify track acquisition has no loose-search setting. Harmony first invokes
SpotDL with the stored Spotify track URL and automatically retries by
artist/title if the provider fails or produces no audio. A successful process
must produce exactly one supported audio file, and Harmony validates embedded
artist/title identity, material recording-version markers, and reliable
duration before the worker can import it.

A zero exit with no audio or an identity rejection is recorded as
`exact_match_unavailable` and is not automatically requeued indefinitely.
Transient provider outcomes remain separately categorized, including rate
limits and provider unavailability. Operators can manually retry the retained
Spotify URL later. There is no environment or runtime option to bypass identity
validation because library accuracy is the invariant.

Rejected temporary output is removed. Harmony does not automatically delete
previously imported Library files; incorrect historic files and associations
must be reviewed and removed manually.

## Artwork

`COVER_ART_ARCHIVE_*` values control remote artwork fetch timeout and response
size for files that already contain a canonical MusicBrainz release ID.

The defaults are conservative for public infrastructure. Fetching artwork
never authorizes canonical metadata changes or file-tag writes.

## Spotify metadata credentials

Harmony no longer calls Spotify solely to enrich artist genres. Existing
embedded or indexed genres remain preserved during download and import. The
optional `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` values are used only
when the official Spotify metadata API is explicitly enabled.

## Source schedules

Source auto-sync is configured per Source in the Sources UI, not through an
environment variable. v2.0.0 offers hourly, 6-hour, 12-hour, daily, and weekly
intervals. Enabling auto-sync also enables the Source.

## Runtime settings

The UI validates bounded settings for Downloads, Cover Art Archive, Navidrome
reconciliation, and the Library
watcher. Invalid updates return HTTP 422 and leave the previous value in place.
General date/time, theme, audio quality, worker, retry, playlist, and export
preferences are also persisted.
