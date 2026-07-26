# Harmony Roadmap

> Baseline: v2.0.1
>
> Last updated: 2026-07-26

The v2.0.1 baseline includes the persistent Library, Metadata Intelligence,
Downloads Operations Center, Spotify and opt-in YouTube Music acquisition,
direct Navidrome playlist synchronization, automatic playlists, per-source
schedules, editable runtime settings, and the mobile-first interface.

## Next

- Backup and restore for the database, settings, playlist definitions, and
  artwork metadata.
- Settings import/export and clearer restart-required state.
- Schedule history, missed-run visibility, and explicit run-now diagnostics.
- Additional metadata providers.
- User-defined smart-playlist and collection rules.
- Favorites, ratings, and tags that can drive automatic collections.
- API authentication and external-integration hardening.

## Later

- Additional media-server APIs beyond Navidrome.
- Apple Music, Deezer, and other acquisition/provider adapters.
- Multi-user permissions and isolated preferences.
- Plugin boundaries for providers and post-processing.
- Lyrics provider acquisition, editing, and synchronized sidecar writing.

## Explicitly shipped

The following items are no longer roadmap promises: YouTube Music downloads,
Cover Art Archive fetches, editable runtime settings, scheduled source sync,
Recently Added/Downloaded auto-playlists, canonical tag writing, and direct
Navidrome playlist synchronization. Explainable duplicate resolution, manual
artwork replacement, local lyrics indexing, and installable/offline-shell PWA
support are also shipped.

The v2.0.1 stabilization release adds automated test and container-build CI,
consolidates database engine/session ownership, and separates lightweight
liveness from database-and-storage readiness probes.
