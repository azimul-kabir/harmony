# Harmony Library Architecture

> Version: 1.7.0
> Status: Implemented Foundation
> Last Updated: 2026-07-21

---

# Overview

The Library Engine is the core of Harmony.

Harmony is **not a music player**.

Harmony's responsibility is to:

- Acquire music
- Organize music
- Maintain metadata
- Keep the library healthy
- Expose the library through APIs

Playback is delegated to applications like Navidrome.

---

# Design Principles

The Library must be:

- Fast
- Reliable
- Incremental
- Extensible
- Source-independent

Never depend on one metadata provider or one download source.

Future integrations include:

- MusicBrainz
- Cover Art Archive
- YouTube Music
- Deezer
- Discogs
- Navidrome

---

# High-Level Architecture

```
Spotify Playlist
        │
        ▼
Download Engine
        │
        ▼
Library Index
        │
 ┌──────┼─────────────┐
 ▼      ▼             ▼
Metadata Artwork   Search Index
        │             │
        ▼             ▼
Collections     Analytics
        │
        ▼
REST API
        │
        ▼
Web UI
```

---

# Library Domain Model

```
Library

├── Artists
│
├── Albums
│
├── Songs
│
├── Artwork
│
├── Playlists
│
├── Sources
│
└── Collections
```

---

# Core Entities

## Song

Represents one audio file.

Fields

- id
- title
- artist_id
- album_id
- track_number
- disc_number
- duration
- bitrate
- codec
- sample_rate
- file_size
- path
- filename
- date_added
- last_modified
- artwork_id
- metadata_status

External IDs

- spotify_id
- musicbrainz_recording_id
- isrc

Relationships

Song

↓

Album

↓

Artist

↓

Artwork

↓

Playlist References

---

## Album

Fields

- id
- title
- artist_id
- year
- genre
- artwork_id

External IDs

- spotify_album_id
- musicbrainz_release_id

Contains

Many Songs

---

## Artist

Fields

- id
- name
- sort_name

External IDs

- spotify_artist_id
- musicbrainz_artist_id

Contains

Many Albums

Many Songs

---

## Artwork

Fields

- id
- cache_path
- source
- checksum
- width
- height

Possible Sources

Embedded

Folder

Spotify

Cover Art Archive

Manual

---

## Playlist

Represents where a song came from.

Fields

- id
- spotify_playlist_id
- name
- owner
- source

A song may belong to multiple playlists.

---

## Collection

Generated automatically.

Examples

Recently Added

Highest Bitrate

Missing Artwork

Duplicate Songs

Favorites

---

# Services

The Library Engine is composed of independent services.

```
LibraryService

MetadataService

ArtworkService

SearchService

CollectionService

AnalyticsService

IndexService

WatcherService

ImportService
```

Each service should have a single responsibility.

---

# Event Flow

Downloads should never update the UI directly.

Everything passes through the Library.

```
Download Completed

↓

Index File

↓

Extract Metadata

↓

Generate Artwork Cache

↓

Update Search Index

↓

Refresh Collections

↓

Refresh Analytics

↓

Notify UI
```

Future

↓

Metadata Repair

↓

Duplicate Detection

↓

Navidrome Sync

---

# Library Index

The Library Index is the source of truth.

The persistent index is the `songs` table. One row represents one managed
audio file and keeps a stable internal ID even when the file becomes missing.
Downloaded files must be indexed through `LibraryService`; download workers,
API routes, and future integrations must not maintain parallel song records.

In addition to descriptive metadata, each indexed file stores technical audio
properties, artwork status, availability, filesystem timestamps, metadata hash,
download source, Spotify/MusicBrainz/ISRC identifiers, and indexing timestamps.
Playlist sources are resolved from the persistent `playlists` and
`playlist_tracks` index using the Spotify track ID. This avoids duplicating
playlist membership on each song row while still exposing it in Library APIs.

Incremental indexing compares file size and modified time before parsing tags.
Unchanged files are skipped. Re-indexing forces tag extraction and compares the
metadata hash. Files absent during reconciliation are marked `missing`, not
deleted, so history, source relationships, and internal IDs remain stable.

Library maintenance API:

- `GET /api/library/songs/{id}` returns one complete index record.
- `GET /api/library/missing` returns retained missing-file records.
- `POST /api/library/index` incrementally indexes one file.
- `POST /api/library/rescan` reconciles the managed library.
- `POST /api/library/reindex` forces a complete metadata rebuild.

Never scan the filesystem unless:

- First startup
- Manual rebuild
- Integrity verification

Normal operation should use incremental updates.

---

# File Watcher

`LibraryWatcher` runs as a supervised background service for the configured
music root. It uses native filesystem notifications through Watchdog and does
not perform periodic full-directory scans.

Supported changes:

- New audio files are incrementally indexed after a short debounce period.
- Deleted audio files are retained in the index and marked `missing`.
- Modified files are forcibly re-read so tag-only changes are detected even
  when file size or timestamp granularity would otherwise hide the change.
- Renamed and moved files update the existing row before re-indexing, preserving
  the stable internal song ID.

Filesystem tools often emit several notifications while a file is being
written. Events are coalesced per path and failed indexing operations are
retried with bounded backoff. A supervisor restarts the native observer if it
stops unexpectedly. Failures and recoveries use the standard Harmony logger.

The watcher publishes transient domain events through `LibraryEventBroker`:

- `library.track.added`
- `library.track.updated`
- `library.track.missing`
- `library.track.renamed`
- `library.index.error`
- `library.watcher.error`
- `library.watcher.recovered`

Consumers can subscribe using `GET /api/library/events`, an SSE endpoint. These
events are notifications, not persistent state; reconnecting consumers must
query the Library Index to reconcile their view.

No full rescans are initiated by the watcher. Manual rescan and re-index
operations remain explicit integrity tools.

---

# Search

Search operates only on the Library Index.

Never search the filesystem.

Harmony's first indexed search engine uses SQLite FTS5. `library_search` is a
derived projection keyed by the stable Song ID; API results are always hydrated
from canonical `songs`, `playlists`, and `playlist_tracks` records. The search
projection contains no file paths and search execution performs no filesystem
access.

The FTS tokenizer is Unicode-aware, removes diacritics, and supports prefix
matching across multiple terms. Results are ordered by BM25 relevance, then by
stable Library metadata. Missing-file rows remain searchable only when the
caller explicitly enables `include_missing`.

The projection is maintained transactionally when a Song is indexed or
re-indexed. Playlist synchronization refreshes only Songs associated with the
changed playlist track IDs. The Alembic migration backfills existing libraries.
`POST /api/library/search/rebuild` is an explicit repair operation; normal
search and watcher activity never initiate a filesystem scan or full rebuild.

Supported search fields

Title

Artist

Album

Genre

Playlist

Spotify ID

MusicBrainz ID

ISRC

Filename

Search API:

- `GET /api/library/search?q=...` returns ranked, paginated Song records.
- Optional filters: artist, album, genre, playlist_id, year, min_bitrate,
  max_bitrate, and include_missing.
- `POST /api/library/search/rebuild` rebuilds the projection from database
  records only.

The web Library search box queries this API with a debounce and projects the
ranked Song matches into the Songs, Albums, and Artists views. Collection names
remain locally filtered UI navigation rather than FTS content.

---

# Artwork

Artwork is a reusable, content-addressed resource. The `artwork` table owns one
row per unique image and Songs reference it through nullable `songs.artwork_id`.
The checksum is a SHA-256 digest of the image bytes and is unique, so identical
embedded or folder images share one database row and one cached file.

Cached files live below the configured `ARTWORK_CACHE_PATH` in checksum-prefix
directories. Cache paths are internal implementation details and are never
returned to API clients. The public immutable URL is
`/api/artwork/{id}/file`. Cache writes are atomic; a database record whose file
was lost is repaired from the next locally detected copy.

Artwork resolution runs as part of Library indexing and uses this priority:

1 Embedded artwork

2 Existing associated cache

3 Folder artwork

4 Future providers (not fetched by the foundation)

- Spotify

- Cover Art Archive

Supported folder filenames are `cover`, `folder`, `front`, and `album` with
JPEG, PNG, or WebP extensions. Embedded images are read through Mutagen from
ID3 APIC, MP4 `covr`, and FLAC picture blocks. Remote `cover_url` values remain
compatible metadata but are never downloaded by `ArtworkService`.

Artwork API:

- `GET /api/artwork` lists resource metadata with offset/limit pagination.
- `GET /api/artwork/{id}` returns one resource's metadata and public URL.
- `GET /api/artwork/{id}/file` serves immutable cached bytes.

The model reserves `provider`, `provider_id`, and `original_url` for future
Spotify and Cover Art Archive provenance. Manual replacement will create or
reuse a content-addressed resource and change an association; it must never
overwrite shared bytes in place. Remote-provider ingestion and manual upload
endpoints are intentionally outside this foundation.

---

# Metadata

Harmony owns metadata.

Future metadata providers

Spotify

MusicBrainz

Discogs

Embedded tags

Manual edits

Every field should include:

Value

Provider

Confidence

Last Updated

---

# Smart Collections

Collections are generated.

Users never manually edit them.

The Library API currently exposes foundation collections at
`GET /api/library/collections`. Counts are calculated exclusively from
available records in the Library Index. The Library web page presents Songs,
Albums, Artists, and Collections as separate views; none of these views scan or
query the filesystem. Selecting a generated collection filters the indexed
Songs projection.

The initial generated collections are Recently Added (seven days), High
Bitrate (320 kbps or higher), Missing Artwork, and Missing Metadata. These are
query-backed views and do not introduce duplicated collection state.

Examples

Recently Added

Recently Downloaded

Missing Metadata

Missing Artwork

High Bitrate

Large Albums

Future

Custom Rules

---

# Analytics

Analytics use the Library Index.

Never calculate directly from the filesystem.

Examples

Song Count

Album Count

Artist Count

Genre Count

Storage

Average Bitrate

Health Score

---

# Duplicate Detection (Future)

Detection priority

Spotify ID

↓

MusicBrainz Recording ID

↓

ISRC

↓

Metadata Match

↓

Audio Fingerprint

Duplicate handling is a separate service.

---

# Multi-Source Downloads (Future)

Harmony separates metadata from audio.

Metadata

Spotify

↓

Audio Source

YouTube Music

↓

Metadata Repair

↓

Library

↓

Playback

Navidrome

---

# Media Server Integration (Future)

Harmony manages the library.

Media servers consume it.

Harmony never becomes a streaming server.

Supported servers

Navidrome

Jellyfin

Subsonic-compatible

---

# Database Design

The database should be normalized.

Recommended tables

artists

albums

songs

artwork

Current `artwork` fields: id, checksum, cache_path, source, mime_type, width,
height, file_size, provider, provider_id, original_url, created_at, updated_at.

playlists

playlist_songs

collections

collection_items

library_events

download_sources

metadata_sources

Future tables

duplicates

metadata_history

play_history

---

# Performance Goals

Library startup:

<5 seconds

Incremental indexing:

<100ms per file

Search:

<50ms

Artwork retrieval:

Instant

Support

100,000+ songs

10,000+ albums

5,000+ artists

---

# Coding Standards

Every new feature should:

Use LibraryService.

Never duplicate metadata parsing.

Never access the filesystem from UI routes.

Use dependency injection.

Keep services independent.

Write unit tests.

Update this document if architecture changes.

---

# Long-Term Vision

Harmony is a **self-hosted music acquisition and library management platform**.

Responsibilities

✓ Download music

✓ Organize music

✓ Maintain metadata

✓ Repair libraries

✓ Manage artwork

✓ Detect duplicates

✓ Generate collections

✓ Expose APIs

✗ Stream music

✗ Play music

Harmony prepares the perfect music library.

Applications like Navidrome provide playback.
