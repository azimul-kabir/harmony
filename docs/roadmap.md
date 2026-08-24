# Harmony Roadmap

> Current release: v3.0.0
>
> Previous stable baseline: v2.1.0
>
> Last updated: 2026-08-21

Harmony v3 deliberately narrows the product around one dependable path:

**Sources → Downloads → Library → M3U/Navidrome**

It is a simplification release, not a database reset. Existing installations
must remain upgradeable, so old migrations and compatibility columns may remain
even when the feature that originally used them is no longer active.

## Completed for v3

- Removed Synology monitoring, Smart Collections, lyrics, detailed Library
  analytics, metadata discovery/application consoles, metadata-health rule
  persistence, generated auto-playlists, Navidrome Love/Unlove operations, and
  automatic Navidrome reconciliation. Optional Spotify artist-genre enrichment
  and its runtime surface are also removed; embedded genres remain intact.
- Reduced Navidrome integration to connection/scan controls and M3U-driven
  playlist delivery.
- Retained authenticated Spotify and public YouTube Music Sources, exact-match
  acquisition, controlled fallback matching, manual fallback, retries,
  provider cooldowns, Library indexing, playlist exports, and the mobile/PWA
  interface.
- Reconciled provider no-match downloads with songs already in the Library,
  kept the details drawer stable during live updates, and removed the blank
  dashboard summary column.

## Completed v3 simplification sequence

The cleanup proceeded in small, independently testable changes:

1. **Removed unreachable application code.** Deleted obsolete routers, services,
   templates, JavaScript, and CSS only after confirming there are no active
   imports, routes, scheduled jobs, or settings references.
   - Initial cleanup removed the unmounted legacy “sync all Sources” endpoint,
     superseded Library/Source compatibility helpers, unused response schemas,
     and placeholder downloader, provider, and metadata-domain abstractions.
     Active Source scheduling, provider-neutral download Sources, the canonical
     Library indexer/import engine, and the file-metadata reader are unchanged.
2. **Contracted the active models.** Stopped reading and writing dormant feature
   fields in runtime code. Keep schema columns needed to open and upgrade an
   existing v2 database; physical database cleanup can wait for a separately
   tested migration in a later release.
   - Removed retired lyrics, Navidrome playback-stat, and Smart Collection
     fields from active ORM models. Historical migrations keep those columns
     intact in upgraded v2 databases, while current queries use source identity
     rather than the removed playlist-kind flag.
   - Removed the retired metadata suggestion, discovery, provider-cache,
     application-audit, and persisted-issue tables from the active ORM schema.
     Existing installations retain their historical tables and data; fresh v3
     databases no longer create unused feature storage.
3. **Retired obsolete settings safely.** Removed unused controls and defaults
   from the UI and runtime settings service while tolerating old rows and
   environment variables during upgrade.
   - Removed the no-op playlist-sync, M3U export-folder, and default download
     source settings. Existing database rows are ignored rather than deleted,
     and retired environment variables remain accepted as extra input.
4. **Pruned tests and documentation by behavior.** Replaced tests for removed
   product surfaces with upgrade-compatibility tests. Keep coverage for login,
   Sources, download matching/recovery, Library import, M3U export, Navidrome
   scans, and mobile/PWA behavior.
5. **Reduced the dependency and image surface.** Removed only packages proven
   unused by static checks and retained all dependencies needed by active paths.

## v3 release validation

- A v2.1.0 database upgrades in place without data loss or manual SQL.
- Existing Library songs, Sources, playlist order, M3U files, login, and runtime
  settings remain usable.
- Exact and controlled-fallback downloads, duplicate skips, manual fallback,
  retries, and cancellation have regression coverage.
- The full Python 3.12 suite passes, the production image builds, and the
  `linux/amd64` image starts with persistent database/music/download mounts.
- Validate each maintenance release on a DS220+-class Synology deployment
  before publishing its version tag.

## After v3

The first post-v3 work should favor operational fundamentals over rebuilding
removed feature suites:

- ✅ Backup and restore for the SQLite database (including settings, Sources,
  and playlists) and cached artwork, available under Settings → Operations.
- ✅ Portable JSON settings import/export with restart guidance; environment
  paths and credentials remain intentionally excluded.
- ✅ Durable automatic/manual schedule history, late-run visibility, and
  run-now outcome diagnostics on each Source.
- API tokens for automation clients beyond browser-session authentication.
- Provider/plugin boundaries only when a second maintained implementation
  proves the abstraction is necessary.

Multi-user permissions, additional media servers, and additional acquisition
providers are intentionally deferred until the smaller v3 core is stable.
