# Harmony Library Architecture

> Version: 1.6.0 (Metadata Intelligence foundation)
> Status: In development
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
- path
- filename
- artist
- album
- album_artist
- title
- track_number
- disc_number
- genre
- year
- duration
- bitrate
- codec
- sample_rate
- file_size
- date_added
- last_modified
- artwork_id
- artwork_status
- availability_status
- download_source

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

Album is currently a grouped read projection over canonical Song rows, keyed by
album name and coalesced album artist. It is not a persistent table or identity.
A future normalized Album entity must be introduced through an additive
migration and preserve Song IDs and existing read contracts.

---

## Artist

Artist is currently a grouped read projection over canonical Song rows. Future
MusicBrainz artist identities and aliases belong in a normalized additive
entity; provider-specific IDs must not become the Library's internal identity.

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

Current canonical boundaries:

- `library_scanner`: filesystem discovery and canonical Song upsert.
- `library_catalog`: typed read-model serialization, eager artwork loading, and
  batched playlist provenance for APIs and future integrations.
- `library_search`: transactional FTS projection maintenance and bounded search.
- `library_filters`: composable query filters and stable sorting.
- `library_predicates`: shared semantic SQL definitions such as missing metadata.
- `collections`, `library_analytics`, and `library_health`: index-only projections.
- `artwork`: content-addressed local artwork detection and storage.
- `library_bulk` and `library_health`: task-backed filesystem orchestration.
- `task_progress`: the shared durable-task API contract.

## Persistent Library Jobs and Activity

Library-changing work uses the existing durable `tasks` table; it is not a
second queue.  Library maintenance and bulk tasks add a resource key, safe
error summary/code, cancellation timestamp, initiator, resumability and
restart metadata. `task_item_failures` retains only the newest 100 concise,
structured failures per job (no tokens, secrets, paths outside the managed
library, or raw exception traces).

Jobs move through `queued`, `running`, `cancelling`, `cancelled`, `completed`,
`completed_with_errors`, `failed`, and `interrupted`. Cancellation is
cooperative between items; a process restart marks non-resumable running
library jobs interrupted rather than guessing that filesystem changes are safe
to repeat. Resource keys reserve `library-files` while queued or active, so
maintenance and bulk file operations cannot modify the same library together.

Stable job APIs are `GET /api/tasks/jobs/active`, `/recent`, `/{id}`, and
`/{id}/failures?offset=&limit=`, `POST /api/tasks/jobs/{id}/cancel`, plus
`GET /api/tasks/library-activity`. Existing maintenance and bulk endpoints
remain compatible and return the legacy progress shape.

At startup, terminal Library history is bounded to the newest 200 jobs; ORM
cascades remove their bulk-item and failure rows. Active jobs are never removed.
The database also enforces a partial unique index for active resource keys so
two concurrent submitters cannot bypass the application-level conflict check.

Compatibility note: this is an additive extension of Harmony's `tasks` table,
Task lifecycle service, and operation-specific workers. Existing task IDs,
download/playlist task types, progress fields, and maintenance/bulk endpoints
remain valid. New job fields and explicit aliases are added to the shared
serializer; no task records were migrated into a second queue.

`library_service`, `scanner`, and `library_manager` remain compatibility facades.
New code must depend on the canonical services above rather than add another
parallel scanner, serializer, path builder, or task response format.

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

Watchdog is a required Harmony runtime dependency, declared in
`pyproject.toml`; the watcher is enabled by default. Production and test
environments must install Harmony from that manifest (use
`python -m pip install -e ".[dev]"` before running the test suite). A missing
Watchdog installation is a deployment dependency error and must be corrected
rather than bypassing watcher coverage.

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
Watcher notifications are best effort: Docker and Synology mounts can coalesce,
delay, duplicate, or omit them, so a manual Refresh Library remains the
integrity-reconciliation path. As defence in depth, events that resolve outside
the configured music root, including symlink escapes, are ignored.

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

## Sorting and Filtering

Library listing and FTS search share the immutable `LibraryFilters` query model.
All supplied filters use AND semantics and execute against indexed database
columns; the UI never filters by reading tags or walking the filesystem.

Supported sorts are Artist, Album, Title, Recently Added, Recently Modified,
Bitrate, Duration, Year, and Alphabetical. Sort keys are allow-listed and use
stable secondary ordering. Supported filters are Artist, Album, Genre, Codec,
Bitrate range, Downloaded Today, Recently Added, Missing Artwork, and Missing
Metadata. Search additionally retains the Playlist, Year, and missing-file
filters exposed by the first FTS API.

`GET /api/library/filter-options` returns the distinct metadata values and
standard bitrate bands used to build filter controls. `GET /api/library/songs`
and `GET /api/library/search` accept the same composable filter parameters.
Downloaded Today uses `songs.created_at` since that is the Library Index's date
added; Recently Added is the rolling seven-day window used elsewhere.

Sort and filter preferences are stored in browser local storage under a
versioned Harmony key. Preferences are presentation state, not shared Library
domain data, and therefore do not require a database table or migration.

Single-column and selective composite indexes cover availability, artist,
album, title, genre, codec, bitrate, year, date added, and last modified. This
keeps common filter/sort plans efficient without duplicating canonical Song
metadata.

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

## Metadata Intelligence foundation

Canonical metadata remains on the existing `songs` Library Index. The
`metadata_suggestions` table is a provider-neutral review queue and never
overwrites a Song merely because a suggestion is created or accepted. The
`metadata_history` table is an immutable applied-change audit log. Neither
table introduces a second library database, stores provider response payloads,
or has a cascading foreign key to Songs; stable entity type/ID references keep
audit data when a file is missing and allow future normalized Album and Artist
entities to use the same model.

Suggestions support competing provider proposals, bounded JSON values and
evidence, confidence and explanation, provenance, durable job attribution, and
review timestamps. A partial unique index permits only one `accepted` or
`applied` suggestion for an entity field. Accepting a newer pending proposal
atomically marks an older accepted proposal `superseded`. Acceptance records a
decision only: canonical rows and audio files remain unchanged in this phase.
Rejections and superseded proposals are retained.

Applied-change history records previous/new values, provider provenance,
confidence, initiating job/source, whether audio was changed, reversibility,
and an optional reversal link. Audit history has no automatic deletion policy.
Operators should retain it for the life of the Library; if storage policy is
later required, it must be explicit, documented, and preserve externally
exported audit records. Structured evidence is limited to 8 KiB per evidence
field and metadata values to 4 KiB. Raw provider responses, secrets, exception
payloads, and audio content are never stored here.

Stable endpoints are:

- `GET /api/library/songs/{id}/metadata`
- `GET /api/library/songs/{id}/metadata/suggestions`
- `GET /api/library/songs/{id}/metadata/history`
- `GET /api/metadata/suggestions/pending`
- `GET /api/metadata/suggestions/{id}`
- `POST /api/metadata/suggestions/{id}/accept`
- `POST /api/metadata/suggestions/{id}/reject`

Metadata discovery or apply work that becomes asynchronous must use the
existing persistent Library Jobs framework and its safe diagnostics. No
provider work is scheduled by this foundation. The Library UI exposes a
provider-neutral per-Song review dialog with canonical values, evidence,
decisions, and applied history. Existing Library API response contracts remain
unchanged.

---

# Smart Collections

Smart Collections are generated live from the Library Index. Users never
manually edit their membership, and no collection-item rows duplicate Song
state. Counts and contents therefore update automatically after normal index or
watcher transactions without a refresh job or filesystem scan.

`CollectionEngine` owns an ordered registry of immutable
`CollectionDefinition` values. Each definition contains presentation metadata
and a serializable `CollectionRule` or nested `RuleGroup`. The rule compiler
currently supports equality, inequality, rolling date windows, missing values,
dynamic maximum values, album song-count thresholds, AND/OR groups, and
placeholders. This registry/compiler boundary is the extension point for future
stored custom rules; UI routes must not implement collection predicates.

Initial collections:

- Recently Added: date added within seven days.
- Recently Downloaded: date added within seven days and download source is not
  `filesystem`.
- Highest Bitrate: tracks matching the current maximum available bitrate.
- Missing Artwork: artwork status is missing.
- Missing Metadata: title, artist, or album is empty.
- Recently Modified: filesystem modification time within seven days.
- Large Albums: albums containing at least ten available indexed songs.
- Favorites: a zero-item placeholder until a favorite signal is introduced.

Collection API:

- `GET /api/library/collections` returns definitions and live counts.
- `GET /api/library/collections/{id}` returns one definition, rule, and count.
- `GET /api/library/collections/{id}/songs` returns live indexed Song records
  and composes with the standard Library sort and filter parameters.

The Library web page renders every registered collection and loads its contents
through the collection API. It never reimplements rules in JavaScript. Selecting
a collection projects its Songs into the existing Songs, Albums, and Artists
views while preserving the current user filters and sort.

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

Library Analytics use available records in the Library Index exclusively.
They never inspect files, parse tags, or walk the filesystem.

`LibraryAnalyticsService` returns one reusable structured snapshot. A single
aggregate query calculates Songs, Artists, Genres, Storage Used, Average
Bitrate, Average Duration, and Recently Added. Album count and the three album
insights use grouped SQL subqueries with indexed ordering and `LIMIT 1`; Song
rows are never materialized in application memory.

Definitions:

- Albums count distinct non-empty album/album-artist groups.
- Storage Used is the sum of indexed file sizes.
- Average Bitrate and Average Duration ignore unknown values.
- Largest Album is the album with the most available Songs, using storage and
  name as stable tie-breakers.
- Newest Album and Oldest Album use indexed release year and ignore albums with
  no year.
- Recently Added is the rolling seven-day count shared with Smart Collections.

`GET /api/library/analytics` exposes the analytics snapshot for dashboards and
future integrations. The Library page loads it independently from song/filter
queries and refreshes it after rescans and Library watcher events. Analytics
therefore remain global when a user narrows the current Library view.

Composite indexes on availability/album/album-artist and
availability/year/album support grouped album insights for large libraries.

Future metrics such as Health Score should be added to this service and API,
not recomputed in UI code.

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

## Large Library Query Policy

The supported design target is at least 100,000 Songs. Services must therefore:

- Use keyset or bounded offset pagination for background iteration and public
  endpoints. List endpoints accept optional `limit` (maximum 1,000) and
  `offset`; existing unbounded defaults remain only for client compatibility.
- Never rebuild FTS one Song at a time. Rebuild uses one `INSERT ... SELECT`
  projection with playlist names pre-aggregated once; incremental updates use
  SQLite-safe batches of at most 500 identifiers.
- Eager-load the to-one Artwork relationship and batch playlist provenance once
  per bounded result page, avoiding serializer N+1 queries.
- Stream scan reconciliation rows in bounded chunks. The discovery path set is
  the only scan-wide in-memory structure and stores strings, not ORM entities.
- Use keyset primary-key iteration for verification and cache maintenance so
  worker memory does not grow with library size.
- Avoid building full directory-entry maps during artwork discovery; retain only
  the fixed set of supported candidate filenames.

Automated coverage asserts that rebuilding 2,500 FTS rows uses a constant number
of SQL statements. Performance-sensitive changes should preserve set-based
plans and be profiled against a generated 100,000-row SQLite fixture.

## API Contracts and Extension Compatibility

FastAPI response models in `app/api/schemas/library.py` document task, bulk, and
health contracts in OpenAPI. Every Library route has a stable summary; bounded
search responses always expose total, limit, offset, filters, and hydrated Song
read models. Internal filesystem paths remain present for backward compatibility
but should be access-controlled before exposing Harmony outside a trusted host.

External systems integrate through provider-neutral boundaries:

- MusicBrainz and metadata repair write canonical fields through the index/upsert
  service and store provider provenance separately when that schema is added.
- YouTube Music is a download source value, never a Library identity.
- Duplicate detection consumes stable Song read models and external identifiers
  without changing search or collection ownership.
- Navidrome consumes available indexed paths and events; it does not write Song
  rows directly.

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

---

# Bulk Operations

Library bulk operations are durable asynchronous Tasks. `tasks` is the parent
progress record and `bulk_operation_items` stores the status, original path,
result path, and error for every selected song. This keeps progress and partial
failures inspectable without coupling the Library UI to worker threads.

Supported operations are delete, move, rename, metadata refresh, artwork cache
refresh, and ZIP export. All operations resolve songs through the Library Index.
UI routes never perform filesystem mutations.

The Library bulk worker:

- Processes one task in the background and checks cancellation between items.
- Continues after item-level failures and records each error independently.
- Marks abandoned non-resumable tasks `interrupted` after process restarts;
  only an operation explicitly marked resumable may return to `queued`.
- Uses paths constrained to the configured music root and never overwrites a
  destination collision.
- Preserves the internal song ID when moving or renaming files.
- Publishes the existing Library events after index-changing operations.

Exports are written beneath `<download_path>/exports` and exposed through an
authenticated-ready API boundary. Export creation reads files only in the
worker; search and normal Library reads remain index-only.

API surface:

- `POST /api/library/bulk` creates a task from an operation, song IDs, and options.
- `GET /api/library/bulk/{task_id}` returns aggregate progress and item results.
- `POST /api/library/bulk/{task_id}/cancel` requests cooperative cancellation.
- `GET /api/library/bulk/{task_id}/export` streams a completed ZIP export.

---

# Library Health

`LibraryHealthService` provides a reusable, index-only health snapshot. It
combines the existing analytics aggregates with registered health checks for
artwork completeness, metadata completeness, and future duplicate detection.
The duplicate check is explicitly unavailable until a detector exists; clients
must not treat the placeholder as a zero-duplicate result.

The Health Score is a bounded 0–100 completeness indicator. Missing metadata,
missing artwork, and missing files currently contribute weighted penalties.
New checks such as metadata confidence, duplicate groups, and repair history
must be added to the service's check registry and score policy, not hard-coded
in the web page. `GET /api/library/health` exposes this stable snapshot shape.

Maintenance actions reuse Harmony Tasks with the `library_maintenance` type and
run in a supervised background worker:

- Refresh Library performs an incremental scan and missing-file reconciliation.
- Rebuild Index forces metadata extraction and rebuilds the FTS projection.
- Verify Files checks indexed paths directly without discovering new files.
- Clear Artwork Cache removes content-addressed files and associations; later
  metadata refreshes can populate them again.

Non-resumable tasks left running recover as `interrupted`, report standard
aggregate progress, and publish `library.health.updated` after completion. API:

- `POST /api/library/health/actions/{action}` queues maintenance.
- `GET /api/library/health/tasks/{task_id}` reports progress.
- `POST /api/library/health/tasks/{task_id}/cancel` requests cancellation.

The `/library/health` dashboard consumes only these APIs. Future metadata repair
and duplicate detection should register checks and actions behind the same
service/API boundaries, preserving the dashboard layout.
