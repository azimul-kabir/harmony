# Harmony Architecture

> Current release: v3.0.0
>
> Last updated: 2026-08-21

Harmony is a FastAPI application with a server-rendered, framework-free web UI,
SQLite persistence, and background workers for downloads, Library maintenance,
playlist export, and scheduled source synchronization.
It owns acquisition and organization; Navidrome or another media server owns
playback.

## System boundaries

```text
Spotify / YouTube Music
                  │
                  ▼
         Harmony API + workers
          │       │        │
          ▼       ▼        ▼
       SQLite   Music   Artwork cache
          │       │
          └── M3U playlists ──► Navidrome / other media servers
```

- **Web/API:** FastAPI routes serve HTML, JSON, OpenAPI, and SSE snapshots.
- **Persistence:** SQLAlchemy 2.0 and Alembic manage the SQLite domain state.
- **Downloads:** provider adapters feed durable queue records and the managed
  music directory. Spotify acquisition tries exact identity first, then permits
  controlled fallback candidates only when identity validation succeeds.
- **Library:** the persistent Song index is the query boundary for browsing,
  search, health, artwork, and bulk work.
- **Playlists:** Harmony stores source order and exports atomic M3Us for
  Navidrome or another media server to scan.
- **Automation:** per-source schedules use the same durable services as
  user-triggered synchronization.
- **UI:** HTML, CSS, and vanilla JavaScript use responsive layouts and surgical
  DOM updates during SSE refreshes.

## Detailed documents

- [Library architecture](architecture/library.md)
- [API guide](api.md)
- [Configuration](configuration.md)
- [Domain model decision](decisions/0001-domain-model.md)
- [Download provider decision](decisions/0002-download-provider.md)

## Operational invariants

- Database sessions are closed predictably, including worker-owned sessions.
- Provider failures are bounded and returned as safe errors.
- Library scanning reads embedded metadata without silently rewriting files.
  The per-song editor is the explicit exception: a user-confirmed save writes
  only supported editable tags and then force-reindexes that one file.
- Playlist exports include only existing files linked through available
  canonical Song associations and are replaced atomically; job completion and
  predicted paths never count as availability.
- Navidrome integration is limited to status, scans, and M3U-driven playlists.
- SSE refreshes patch stable UI regions and do not replace active controls.
