# Configuration

## Optional Spotify genre enrichment

`SPOTIFY_GENRE_ENRICHMENT_ENABLED` is `false` by default. Harmony therefore does not create a Spotify client, authenticate, request a token, or call a Spotify API endpoint merely to download, tag, resolve metadata, or index the library. MusicBrainz enrichment and genres embedded in audio files continue to work without Spotify.

To use Spotify artist metadata as an additional, best-effort genre source, set the flag to `true` and configure both credentials:

```env
SPOTIFY_GENRE_ENRICHMENT_ENABLED=false
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
```

Spotify genres can be empty or unavailable. A missing credential or provider failure is non-fatal and never blocks a download. Existing genres and their provenance are retained when the feature is disabled. The precedence is: user-provided genre, MusicBrainz genre, enabled Spotify genre, embedded genre, then empty.
