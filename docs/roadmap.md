# Harmony Roadmap

> Stable baseline: v2.1.0
>
> Next release: v3.0.0
>
> Last updated: 2026-08-12

Harmony v3 deliberately narrows the product around one dependable path:

**Sources → Downloads → Library → M3U/Navidrome**

It is a simplification release, not a database reset. Existing installations
must remain upgradeable, so old migrations and compatibility columns may remain
even when the feature that originally used them is no longer active.

## Completed for v3

- Removed Synology monitoring, Smart Collections, lyrics, detailed Library
  analytics, metadata discovery/application consoles, metadata-health rule
  persistence, generated auto-playlists, Navidrome Love/Unlove operations, and
  automatic Navidrome reconciliation.
- Reduced Navidrome integration to connection/scan controls and M3U-driven
  playlist delivery.
- Retained authenticated Spotify and public YouTube Music Sources, exact-match
  acquisition, controlled fallback matching, manual fallback, retries,
  provider cooldowns, Library indexing, playlist exports, and the mobile/PWA
  interface.
- Reconciled provider no-match downloads with songs already in the Library,
  kept the details drawer stable during live updates, and removed the blank
  dashboard summary column.

## Remaining v3 simplification

Work should proceed in small, independently testable changes rather than a
single destructive deletion:

1. **Remove unreachable application code.** Delete obsolete routers, services,
   templates, JavaScript, and CSS only after confirming there are no active
   imports, routes, scheduled jobs, or settings references.
2. **Contract the active models.** Stop reading and writing dormant feature
   fields in runtime code. Keep schema columns needed to open and upgrade an
   existing v2 database; physical database cleanup can wait for a separately
   tested migration in a later release.
3. **Retire obsolete settings safely.** Remove unused controls and defaults
   from the UI and runtime settings service while tolerating old rows and
   environment variables during upgrade.
4. **Prune tests and documentation by behavior.** Replace tests for removed
   product surfaces with upgrade-compatibility tests. Keep coverage for login,
   Sources, download matching/recovery, Library import, M3U export, Navidrome
   scans, and mobile/PWA behavior.
5. **Reduce the dependency and image surface.** Remove a package only after
   static import checks and a clean production container build show that no
   retained path needs it.

## v3 release gates

- A v2.1.0 database upgrades in place without data loss or manual SQL.
- Existing Library songs, Sources, playlist order, M3U files, login, and runtime
  settings remain usable.
- Exact and controlled-fallback downloads, duplicate skips, manual fallback,
  retries, and cancellation have regression coverage.
- The full Python 3.12 suite passes, the production image builds, and the
  `linux/amd64` image starts with persistent database/music/download mounts.
- The preview is validated on a DS220+-class Synology deployment before a v3
  tag is published.

## After v3

The first post-v3 work should favor operational fundamentals over rebuilding
removed feature suites:

- Backup and restore for database, settings, Sources, playlists, and artwork.
- Settings import/export and clearer restart-required state.
- Schedule history, missed-run visibility, and explicit run-now diagnostics.
- API tokens for automation clients beyond browser-session authentication.
- Provider/plugin boundaries only when a second maintained implementation
  proves the abstraction is necessary.

Multi-user permissions, additional media servers, and additional acquisition
providers are intentionally deferred until the smaller v3 core is stable.
