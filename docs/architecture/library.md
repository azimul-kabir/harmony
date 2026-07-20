# Harmony Library Architecture

> Version: 1.5.1
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

The watcher monitors:

New files

Deleted files

Modified files

Renamed files

The watcher updates the Library Index.

No full rescans.

---

# Search

Search operates only on the Library Index.

Never search the filesystem.

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

---

# Artwork

Artwork priority

1 Embedded artwork

2 Cached artwork

3 Folder artwork

4 Future providers

- Spotify

- Cover Art Archive

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
