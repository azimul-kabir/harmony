# Harmony Library Architecture

> Version: 1.6.0 (Metadata Intelligence foundation)
> Status: Released in v1.6.0
> Last Updated: 2026-07-22

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
- track_total
- disc_number
- disc_total
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
- musicbrainz_release_id
- musicbrainz_artist_id
- isrc

Additional indexed release context includes a nullable compilation marker.

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

## Metadata Health Engine

`MetadataHealthService` evaluates registered, provider-neutral rules against
canonical `Song` rows and grouped projections; it never opens audio files or
contacts external providers. Findings are durable `metadata_issues` records
with deterministic identities, so repeated analysis updates a finding rather
than duplicating it. Open findings absent from a subsequent scoped analysis are
resolved; ignored findings remain ignored. Missing-song rows deliberately have
no foreign key from issues, retaining audit history. Full-library analysis is a
durable Library Maintenance job with the `library-metadata-health` resource
key. The diagnostic score caps each entity's penalty and excludes ignored and
missing songs; it is not a claim of metadata correctness.

Album projection identities are `normalized(album_artist or artist)::normalized(album)`.
Artist identities are normalized canonical artist strings with only a leading
`The` treated as equivalent; featured-artist tokens and version markers are
retained. These keys are projection identities, not future normalized IDs.

## Metadata Matching and Confidence Engine

Metadata matching is a provider-neutral read pipeline:

```
canonical Library projection -> bounded provider searches -> normalized candidates
 -> deterministic scorer -> durable ranked discovery -> explicit selection
 -> explicit pending field-level suggestions
```

Provider retrieval, matching, persistence, suggestion generation, and future
metadata application are separate layers. The scorer imports only normalized
`RecordingCandidate`, `ReleaseCandidate`, and `ArtistCandidate` models. It never
sees MusicBrainz response objects or raw payloads. Discovery neither changes a
Song nor opens an audio file, and selection does not imply metadata acceptance.

Public discovery is Song-only in v1.6.0. Album and artist projection scorers
remain internal because those projections do not yet have normalized persistent
identities. Public attempts to use unsupported entity scopes return
`unsupported_entity_type`; no partially functional album/artist workflow is
advertised.

### Search strategy and bounds

Song searches run in stable order: existing provider recording ID lookup, ISRC,
exact title plus artist, title plus artist plus album, title plus album artist,
and conservative normalized title plus artist. At most six variants run, each
returns at most 10 candidates, at most 40 unique provider/entity identities are
considered, and at most 15 ranked results are retained. Results are deduplicated
by provider and provider entity ID while preserving every search label that
found them. A failed variant is retained as a bounded safe error and does not
discard candidates from successful variants. Filename is diagnostic only.

### Song scoring

The `deterministic-2026-07` score normalizes available weighted evidence onto
0–100; unavailable evidence is neutral and produces a structured explanation.

| Evidence | Weight / behavior |
| --- | --- |
| Exact ISRC | 36; a conflicting supplied ISRC rejects |
| Existing provider recording ID | 40; a conflict rejects |
| Title | 26, similarity weighted; severe contradiction rejects |
| Full artist credit | 22, similarity weighted; featured artists are retained |
| Album | 6; mismatch has only a limited penalty |
| Album artist | 4; unavailable is neutral |
| Duration | 8 within 3 seconds, half within 10 seconds; over 90 seconds rejects |
| Track / disc | 3 / 2; mismatch is contextual |
| Release year | 3; adjacent years receive partial evidence |
| Version markers | +4 agreement; incompatible markers reject with a 30-point penalty |
| Compilation context | 2 agreement; mismatch has a one-point contextual penalty |

Identity-significant markers are live, remix, remaster/remastered, acoustic,
instrumental, karaoke, demo, edit/radio edit, extended, mono, stereo, cover,
anniversary, and deluxe. They are never removed by normalization. Album and
artist projection scoring uses the same result/evidence framework but is
initially conservative.

Thresholds are configurable: exact 97–100, high 88–96, medium 72–87, low
50–71, rejected below 50 or on hard contradiction. Exact additionally requires
an exact ISRC or existing provider ID and no contradiction; fuzzy text alone
cannot be exact. Ranking is score descending, then provider and provider entity
ID as documented stable tie-breakers. Scores within three points are ambiguous;
an exact label is downgraded while ambiguous. Low and ambiguous selection needs
explicit confirmation, and rejected results cannot be selected.

### Persistence and lifecycle

`metadata_discoveries` retains entity/key, provider, status, selected result,
ambiguity, timestamps, job linkage, version fields, bounded query summary, and
bounded safe failures. A SHA-256 snapshot of identity-relevant canonical Song
columns marks a result stale if those columns change later; it contains no path.
`metadata_match_results` retains candidate summaries,
rank/score/confidence, viability, structured evidence, rejection reasons, and
search provenance. Neither table references a Song, so missing-song audit data
survives. Raw provider payloads and local paths are never stored. Common entity,
provider, status, job, timestamp, score, and confidence paths are indexed.

Operators should periodically remove old unselected discoveries according to
deployment needs; selected discoveries and discoveries referenced by pending
suggestions must be retained. The service retains no more than 15 results per
discovery. Rerun creates a new auditable session rather than overwriting one.

Suggestion generation is a separate explicit operation on a selected viable
result. It creates only supported, present, changed field values, remains
pending, preserves discovery/result/job IDs plus provider/score/evidence
provenance, and suppresses an equivalent pending suggestion. Field failures are
reported separately without removing successful field suggestions. It never
accepts or applies a suggestion.

### Durable discovery jobs and locking

Starting discovery creates the `Task`, per-Song `MetadataDiscovery` rows, and
per-Song reservations in one transaction, then returns immediately. The
existing Library Maintenance worker owns provider I/O and scoring; no second
queue or executor exists. A database transaction is committed before each
network sequence. Cancellation is checked between Songs and provider variants.
Successful variants survive bounded failures, and per-Song results commit
independently. Provider-variant errors yield `completed_with_errors`; isolated
Song failures also yield `completed_with_errors`; only an unexpected job-level
failure is `failed`. Process restarts use the existing non-resumable
`interrupted` behavior and release abandoned reservations.

`metadata_discovery_locks` has one primary-key row per Song and references its
active task. This transactionally rejects single or batch scopes overlapping
any active discovery while unrelated Songs remain concurrent. The stable error
is `discovery_conflict` and its message identifies the active job when known.
Queued cancellation and terminal/restart handling release locks. Future
metadata-writing jobs must reserve/check the same per-Song lock boundary;
ordinary read-only browsing and search take no lock.

Selected-Song requests sort and deduplicate IDs, cap the scope at the configured
maximum (500 by default), and are processed in bounded order without loading
the full Library. Health discovery is explicit and resolves supported open
song, album-projection, and artist-projection issues into a bounded deduplicated
Song scope. Health analysis never starts discovery, and discovery never changes
issue state.

Normalized recording candidates now include album artist, track/disc totals,
release/original dates and year, ISRC, compilation context, recording/release
disambiguation, recording artist/release artist IDs, release/release-group IDs,
and the conservative release context used. MusicBrainz parsing remains inside
the provider. Search responses use the first normalized release supplied by
MusicBrainz and record `first_normalized_release`; absent or ambiguous values
remain absent. Cache normalization version `ws2-normalization-v2` prevents old
schema entries from being reused as current candidates.

Stable additive APIs below `/api/metadata/discoveries` are:

- `POST /songs/{song_id}`: queue one Song and return job/discovery linkage.
- `POST /songs`: queue an explicit selected-Song scope.
- `POST /health-rules` and `/health-issues`: queue explicit health scopes.
- `GET /`: paginate and filter durable discoveries.
- `GET /{id}`: retrieve state, stale flag, and ranked candidates.
- `POST /{id}/rerun`: queue a new auditable discovery.
- `POST /{id}/select` and `DELETE /{id}/selection`: manage selection.
- `POST /{id}/suggestions`: explicitly create pending field suggestions.
- `GET /{id}/compare`: compare two persisted candidate explanations.
- `GET /capabilities`: retrieve public boundary, versions, thresholds, and bounds.

Job polling, cancellation, safe failures, and Activity use the unchanged
`/api/tasks/jobs/...` and `/api/tasks/library-activity` contracts. The Song
dialog queues and polls jobs, supports cancellation/retry, reports partial,
interrupted, no-result and stale states, compares two results, confirms weak or
ambiguous selection, and keeps Select separate from Generate Suggestions.
Responses use the existing structured domain error envelope. The original
Provider, Metadata, Health, Library, and Jobs API contracts remain additive and
compatible.

### Rule registration and execution

Rules are described by immutable `RuleDefinition` records and registered with
`MetadataHealthService`. A definition supplies the stable rule ID, version,
scope, severity, explanation, and suggested action. Detectors consume only
canonical `Song` columns and in-memory album/artist projections. Registration
is deliberately provider-neutral: a future provider-backed detector can add a
rule definition without changing issue, score, API, or UI contracts.

The initial registry contains 20 song rules, 13 album rules, and 4 artist
rules. Missing MusicBrainz recording, release, and artist IDs are informational.
Invalid numeric values are errors. All other initial findings are warnings.
No initial rule writes tags or creates a `MetadataSuggestion`.

Comparison normalization uses Unicode NFKC, trims boundary whitespace,
collapses repeated whitespace, case-folds text, and canonicalizes common quote,
dash, and separator punctuation. Artist comparisons may treat a leading
`The` as equivalent. Featured-artist tokens and track version markers are
retained. Normalized values are diagnostic data and never replace canonical
values automatically.

Implausible duration, track/disc maximums, and allowed future-year tolerance
are constructor-configurable thresholds. Defaults are eight hours, track 999,
disc 99, and one future year; the current year itself is always valid.

### Persistence and lifecycle

`metadata_issues` is additive and has no `Song` foreign key by design. Its
SHA-256 identity covers rule/version, entity projection, field, and bounded
rule evidence. Re-detection updates `last_detected_at`; absent open findings
resolve; recurrence reopens resolved findings; ignored findings stay ignored
until explicitly restored. Evidence is JSON limited to 20 values and 2 KB and
never contains raw tag dumps or exceptions. Indexes cover identity, common
status/severity/rule filters, entity lookup, and first/last detection times.

### Jobs and performance

Full analysis is a persistent Library Maintenance job using resource key
`library-metadata-health`. It counts available songs as successful or failed
and missing songs as skipped, supports cooperative cancellation, and records
bounded `METADATA_ANALYSIS_FAILED` item failures. A job with isolated failures
ends `completed_with_errors`; an unexpected engine-level failure ends `failed`.
Search remains read-only and does not reserve the metadata-health resource.

Normal analysis never opens audio files. Song rows are streamed by primary key
for progress/cancellation, while album and artist projections are built from a
single indexed query. Issue endpoints are paginated, and summary/score queries
aggregate once per request rather than once per rendered row.

### Diagnostic score

The metadata score is deterministic from 0–100. Open informational, warning,
error, and critical issues have weights `0.25`, `2`, `6`, and `12`. The summed
penalty is capped at 20 per entity/projection, then measured against a budget of
10 points per available song. Ignored issues and issues attached to missing
songs are excluded and separately counted. The API returns the score together
with weights, counts, cap, penalty, and budget. This is a diagnostic prioritizing
signal, not a claim that metadata is correct.

### Additive APIs

Metadata health endpoints live below `/api/library/health/metadata`: start a
full job; analyze a song, album, or artist; paginate/filter issues; retrieve,
ignore, restore, or resolve an issue; obtain multidimensional summary and score
inputs; and enumerate rule definitions. These routes do not alter the existing
Library Health snapshot contract or metadata suggestion/history contracts.

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

4 Cover Art Archive front artwork, when a user explicitly selects **Fetch
album art** for a Song with an accepted MusicBrainz release ID

5 Future providers

- Spotify

Supported folder filenames are `cover`, `folder`, `front`, and `album` with
JPEG, PNG, or WebP extensions. Embedded images are read through Mutagen from
ID3 APIC, MP4 `covr`, and FLAC picture blocks. Remote `cover_url` values remain
compatible metadata but are never downloaded by `ArtworkService`. Cover Art
Archive downloads use the MusicBrainz release ID, validate that the response is
a JPEG, PNG, or WebP image, and store the result in the same local cache with
provider provenance. Downloads are opt-in bulk operations; scanning a library
never performs remote artwork requests.

Artwork API:

- `GET /api/artwork` lists resource metadata with offset/limit pagination.
- `GET /api/artwork/{id}` returns one resource's metadata and public URL.
- `GET /api/artwork/{id}/file` serves immutable cached bytes.

The model stores `provider`, `provider_id`, and `original_url` for Cover Art
Archive provenance and future providers. Manual replacement will create or
reuse a content-addressed resource and change an association; it must never
overwrite shared bytes in place. Manual upload
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

---

# Canonical Metadata Application

Accepted metadata is applied only to canonical `Song` database columns by a
durable `library_maintenance` Task. The application service never opens an
audio file, writes tags, downloads artwork, calls a provider, or accepts a
suggestion. Each submitted scope receives an application batch and a per-Song
reservation. Reservations prevent overlapping application, rollback, and
discovery scopes, while unrelated Songs can proceed independently.

The request transaction creates the Task, batch, and reservations, then
returns. The maintenance worker performs one Song at a time, commits each Song
and its immutable `MetadataHistory` record, refreshes that Song's FTS row, and
runs only scoped health/projection reconciliation. Cancellation is cooperative
between Songs. Terminal Tasks release reservations; queued cancellation and
restart recovery also update the linked batch to `cancelled` or `interrupted`.
Application batches use `completed`, `completed_with_errors`, `cancelled`,
`failed`, and `interrupted`. Rollback batches use `rolled_back` or
`partially_rolled_back`; rollback creates a new reversal history row and never
edits or deletes the original row.

Stable API surface:

- `GET|POST /api/library/songs/{song_id}/metadata/application-preview` previews
  all accepted or explicitly selected suggestions without queuing work.
- `POST /api/library/songs/{song_id}/metadata/apply` and
  `POST /api/library/songs/{song_id}/metadata/apply-selected` queue application.
- `POST /api/metadata/applications/apply` queues accepted metadata for an
  explicit selected-Song scope.
- `GET /api/metadata/batches`, `GET /api/metadata/batches/{batch_id}`, and
  `GET /api/metadata/batches/{batch_id}/results` expose paginated batch data.
- `GET /api/metadata/history` and `GET /api/metadata/history/{history_id}`
  expose read-only, paginated audit history.
- `GET /api/metadata/history/{history_id}/rollback-preview`,
  `POST /api/metadata/history/{history_id}/rollback`, and
  `POST /api/metadata/batches/{batch_id}/rollback` provide reversible rollback.
- `GET /api/metadata/application/capabilities` advertises supported fields;
  `GET /api/tasks/jobs/{task_id}` and `POST /api/tasks/jobs/{task_id}/cancel`
  are authoritative for progress and cancellation.

Errors use `{ "error": { "code", "message" } }`. Application callers can
rely on `song_not_found`, `suggestion_not_found`, `application_conflict`,
`stale_suggestion`, `invalid_metadata_value`, `unsupported_metadata_field`,
`no_applicable_suggestions`, `history_not_found`, `rollback_not_reversible`,
`rollback_conflict`, and `force_confirmation_required`. Conflict messages name
the active Task when one is available without exposing paths or provider data.
