# Harmony Architecture

> Release baseline: v2.0.0
>
> Last updated: 2026-07-24

Harmony is a FastAPI application with a server-rendered, framework-free web UI,
SQLite persistence, and background workers for downloads, Library maintenance,
metadata work, playlist reconciliation, and scheduled source synchronization.
It owns acquisition and organization; Navidrome or another media server owns
playback.

## System boundaries

```text
Spotify / YouTube Music / MusicBrainz
                  │
                  ▼
         Harmony API + workers
          │       │        │
          ▼       ▼        ▼
       SQLite   Music   Artwork cache
          │       │
          └── M3U playlists ──► Navidrome / other media servers
                     └────────► Navidrome Subsonic playlist API
```

- **Web/API:** FastAPI routes serve HTML, JSON, OpenAPI, and SSE snapshots.
- **Persistence:** SQLAlchemy 2.0 and Alembic manage the SQLite domain state.
- **Downloads:** provider adapters feed durable queue records and the managed
  music directory.
- **Library:** the persistent Song index is the query boundary for browsing,
  search, collections, analytics, health, metadata, artwork, and bulk work.
- **Playlists:** Harmony stores source order, exports atomic M3Us, and can
  reconcile stable Navidrome song/playlist IDs directly.
- **Automation:** auto-playlists and per-source schedules use the same durable
  services as user-triggered operations.
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
- Metadata discovery never silently changes canonical data or file tags.
- Canonical metadata application and audio-file tag writing are separate,
  explicitly confirmed operations.
- Playlist exports include only available files and are replaced atomically.
- Direct Navidrome playlist updates are verified and fall back to M3U import.
- SSE refreshes patch stable UI regions and do not replace active controls.
