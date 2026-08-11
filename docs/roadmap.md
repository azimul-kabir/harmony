# Harmony Roadmap

> Baseline: v2.1.0
>
> Last updated: 2026-08-08

The v2.1.0 baseline includes the persistent Library, Metadata Intelligence,
Downloads Operations Center, authenticated web access, Spotify and opt-in
YouTube Music acquisition and playlist Sources, direct Navidrome playlist
synchronization and health checks, automatic playlists, per-source schedules,
editable runtime settings, and the mobile-first interface.

## Next

- Backup and restore for the database, settings, playlist definitions, and
  artwork metadata.
- Settings import/export and clearer restart-required state.
- Schedule history, missed-run visibility, and explicit run-now diagnostics.
- Additional metadata providers.
- User-defined smart-playlist and collection rules.
- Favorites, ratings, and tags that can drive automatic collections.
- API tokens for external automation clients beyond browser-session
  authentication.

## Later

- Additional media-server APIs beyond Navidrome.
- Apple Music, Deezer, and other acquisition/provider adapters.
- Multi-user permissions and isolated preferences.
- Plugin boundaries for providers and post-processing.

## Explicitly shipped

The following items are no longer roadmap promises: YouTube Music downloads,
Cover Art Archive fetches, editable runtime settings, scheduled source sync,
canonical tag writing and direct
Navidrome playlist synchronization. Explainable duplicate resolution, manual
artwork replacement and installable/offline-shell PWA
support are also shipped.

The v2.0.1 stabilization release adds automated test and container-build CI,
consolidates database engine/session ownership, and separates lightweight
liveness from database-and-storage readiness probes.

The v2.1.0 release adds the signed-session web login, public YouTube Music
playlist Sources, Navidrome Love/Unlove batches, playback-statistics
synchronization health and scan controls, and stricter
provider-output validation.
