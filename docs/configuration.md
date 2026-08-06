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

The same optional credentials enable Spotify as an explicit, review-first
Metadata Intelligence provider independently of genre enrichment. Selecting
Spotify permits bounded recording search and lookup. Merely configuring
credentials never makes scanning, indexing, or ordinary downloads contact
Spotify, and Spotify candidates never populate MusicBrainz identifier fields.

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
# Synology NAS health monitoring

Enable SNMP in DSM under **Control Panel → Terminal & SNMP → SNMP**, enable
SNMPv2c, and configure a read-only community. Set
`SYNOLOGY_MONITORING_ENABLED=true`, `SYNOLOGY_SNMP_HOST` to an address reachable
from the Harmony container, and `SYNOLOGY_SNMP_COMMUNITY` to that community.
Port, timeout, retries, polling interval, stale threshold, and the maximum disk
index can be adjusted with the corresponding variables in `.env.example`.

Harmony uses PySNMP directly; it neither mounts the Docker socket nor invokes
command-line SNMP programs. Only normalized system and disk health is exposed.
The community, raw OIDs, SNMP responses, and internal exception details remain
server-private. If DSM is unreachable, the last successful sample remains
visible and is marked unavailable or stale.

Disk discovery deliberately probes indexed columns with bounded GET requests
from index `.0` through `SYNOLOGY_DISK_MAX_INDEX` (default `.15`). Some DSM
versions return no disk rows from an SNMP walk even though indexed GET requests
work. Missing indexes are ignored, and DSM's returned disk ID—not the SNMP
index—is the displayed disk label.

# Internet-safe local authentication

Authentication is explicitly controlled by `AUTH_ENABLED` and defaults to `false`. Disabled mode preserves the pre-login LAN behavior. Enabled mode has no localhost, LAN, VPN, header, or query-string bypass and fails startup when its secret or first administrator is missing. Usernames are Unicode case-insensitive (`casefold`) and passwords must contain at least 12 characters; long passphrases and spaces are supported without composition rules.

## Safe upgrade from `codex/add-login`

1. Back up `/database/harmony.db` and the environment file. Retain both for rollback (stop Harmony, restore both, then deploy the old image).
2. Deploy this version with `AUTH_ENABLED=false`; startup applies Alembic revision `20260806_0027`. Verify LAN behavior and health.
3. Generate two secrets with `openssl rand -base64 48`, store them in host-readable files, and mount them read-only into `/run/secrets`.
4. While firewall/LAN restricted, configure the bootstrap username/password file and independent session-secret file, then set `AUTH_ENABLED=true`. Verify login/logout, API 401, CSRF mutations, SSE, PWA, and health.
5. Remove `AUTH_BOOTSTRAP_PASSWORD[_FILE]` after first startup. Restart never overwrites an account, but lingering bootstrap material is unnecessary. Keep `AUTH_SESSION_SECRET[_FILE]` stable; changing it invalidates all bearer and CSRF tokens.
6. Configure HTTPS and secure cookies, expose only the HTTPS reverse proxy, and retain trusted-host recovery. **Never expose port 8080 directly to the internet.**

`WEB_AUTH_USERNAME`, `WEB_AUTH_PASSWORD`, `WEB_AUTH_SESSION_HOURS`, and `WEB_AUTH_SECURE_COOKIE` are deprecated and ignored. The prototype plaintext password is deliberately not silently converted. Put it in a new bootstrap secret file only if it meets policy, enable auth once, then remove all legacy and bootstrap password settings.

## Secrets and sessions

File-backed values are preferred. Defining both direct and `_FILE` forms is an error. Secret files are UTF-8 and only trailing CR/LF is removed; spaces remain valid. `AUTH_SESSION_SECRET` requires at least 32 bytes and keys database token/CSRF digests. Browsers receive random bearer tokens while SQLite stores only keyed SHA-256 digests. Sessions expire after `AUTH_SESSION_ABSOLUTE_HOURS` (1–168) or `AUTH_SESSION_IDLE_MINUTES` (5–1440); idle timestamps update at most every five minutes. Logout revokes the record and clears browser/cache state.

HTTPS requires `AUTH_COOKIE_SECURE=true` (default). Trusted direct-HTTP development/LAN access may explicitly use `false`; never use that configuration publicly. `SameSite=lax` is the default, supplemented by synchronized CSRF and Origin validation.

## Docker and Synology

```yaml
volumes:
  - ./secrets:/run/secrets:ro
environment:
  AUTH_ENABLED: "true"
  AUTH_BOOTSTRAP_USERNAME: admin
  AUTH_BOOTSTRAP_PASSWORD_FILE: /run/secrets/harmony_admin_password
  AUTH_SESSION_SECRET_FILE: /run/secrets/harmony_session_secret
  AUTH_COOKIE_SECURE: "true"
  AUTH_TRUSTED_PROXIES: 172.20.0.1
```

In Synology Container Manager create the read-only mount and variables. In Login Portal / Reverse Proxy forward the original `Host`, set `X-Forwarded-Proto: https`, target internal HTTP, disable response buffering for SSE, and use a long read timeout. Trust only the immediate proxy address with `AUTH_TRUSTED_PROXIES`; Uvicorn must use matching `--forwarded-allow-ips`. Never use `*`. Untrusted forwarded addresses are ignored by login throttling, and relative redirects avoid leaking internal names.

The bounded rolling limiter keys failures by normalized user and trusted address and uses temporary 429 cooldowns. It is process-local; multiple Uvicorn workers require shared limiter state. Supported Compose runs one worker.

## Trusted-host recovery

There is no public reset endpoint. Restrict public access, create a root-readable recovery passphrase file, and run:

```bash
docker compose exec -e HARMONY_RECOVERY_PASSWORD_FILE=/run/secrets/recovery harmony python -m app.cli.auth reset-password admin
```

This Argon2id-rehashes the password, increments `session_version`, and revokes all sessions. Delete the file afterward. Back up SQLite before migration; downgrade removes only auth tables and requires disabling auth before rollback.
