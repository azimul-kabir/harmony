# Spotify download and embedded-metadata audit

**Audit scope:** Harmony's Spotify track, album, and playlist queue paths; the
SpotDL 4.5.2 invocation; download validation; download-time tag mutation; import
and indexing. This is a static code audit, not a claim that every audio provider
will return a playable match for every Spotify item.

## Executive summary

All three supported Spotify URL types ultimately create one durable job per
track and use the same `SpotDLClient.download()` path. That is a good design:
album and playlist downloads do not have a less-validated bulk-download bypass.
Every produced file must be the only supported audio output and must match the
requested title, artist, version markers, and duration before it leaves the
temporary directory.

Metadata embedding, however, is owned principally by SpotDL rather than by
Harmony. Harmony explicitly writes only its enriched genre before import.
Consequently, the exact embedded fields depend on SpotDL, output format, and
which upstream fields are available. Harmony persists richer queue metadata,
but it does not reconcile that canonical snapshot into the downloaded file.

The highest-value improvements are:

1. add a format-aware, atomic post-download canonical tag writer and verifier;
2. retain album totals, disc totals, full release date, Spotify album ID, and
   explicit/compilation data in Harmony's track/job model;
3. fix format-aware external-ID reads (notably MP3 `TSRC` and Spotify URL);
4. test actual MP3, M4A, FLAC, OGG, and Opus fixtures rather than trusting the
   provider's tagging implementation.

## Download-path audit

### Single track

1. `POST /api/downloads` parses the URL as `track`.
2. Harmony resolves the Spotify Web API track payload and enriches artist
   genres.
3. One durable job snapshots the resolved fields.
4. The worker asks SpotDL for the Spotify URL. If that attempt fails or produces
   no file, it tries a metadata search.
5. Harmony accepts exactly one audio file only after identity validation, writes
   the enriched genre when available, imports it, indexes its embedded tags,
   and links the indexed song to the Spotify track ID in the database.

**Assessment:** strongest metadata input path. The Web API response supplies an
ISRC and album ID. The final file still relies on SpotDL re-resolving metadata;
the queue snapshot is not used to repair or verify tags.

### Album

1. The API parses the URL as `album` and resolves the album through the Spotify
   Web API.
2. Harmony creates a task and one job for every not-owned/not-queued track.
3. Every child job follows the same validated single-track worker path.

**Assessment:** audio validation is equivalent to a single track. Metadata
resolution is weaker: Spotify's simplified album-track objects are mapped with
`isrc=None`, and Harmony does not fetch full track objects to fill it. Track and
disc numbers are retained, but totals and the full release date are discarded.
The subsequent SpotDL invocation may independently recover those fields for the
file, but Harmony cannot guarantee or verify that it did.

### Playlist

1. The API parses the URL as `playlist`.
2. Playlist metadata is obtained with `spotdl save`, including paging performed
   by SpotDL, then validated into Harmony models.
3. Harmony saves the database playlist, exports its M3U, and queues each
   not-owned track with its playlist position.
4. Every child job follows the same validated single-track worker path.

**Assessment:** audio validation is equivalent to a single track. Playlist
membership/order is database and M3U metadata, not audio-file metadata (which is
correct). The mapper drops SpotDL's available `album_id`, `artist_id`, artists
list, and list position/length when creating a `Track`. Playlist position is
separately passed to the job, so ordering is not lost, but album identity and
multi-artist fidelity in Harmony's snapshot are incomplete.

## What is currently embedded

The following table describes the effective download result with the pinned
SpotDL 4.5.2 implementation. “SpotDL” means Harmony does not independently
guarantee the value. Optional values are omitted when unavailable upstream.

| Field | MP3 | M4A | FLAC / OGG / Opus | Harmony action |
| --- | --- | --- | --- | --- |
| Title | `TIT2` | `©nam` | `title` | Used for validation and import |
| Artists | `TPE1` | `©ART` | `artist` | First/easy value used by Harmony |
| Album artist | `TPE2` | `aART` | `albumartist` | Imported |
| Album | `TALB` | `©alb` | `album` | Imported |
| Release date/year | `TDRC` plus `TYER` | `©day` | `date` | Harmony imports only integer year |
| Track number/total | `TRCK` (`n/total`) | `trkn` tuple | `tracknumber`, `tracktotal` | Imported when readable |
| Disc number/total | `TPOS` (`n/total`) | `disk` tuple | `discnumber`, `disctotal` | Imported when readable |
| Genre | `TCON` | `©gen` | `genre` | SpotDL writes its first genre; Harmony then replaces it with its enriched genre list when available |
| Publisher/encoded by | `TENC` | `©too` | `encodedby` | Not imported into Harmony |
| Copyright | `TCOP` | `cprt` | `copyright` | Not imported |
| Spotify URL | `WOAS` | freeform `spotdl:WOAS` | `woas` | Not imported as a tag identity |
| Provider/download URL | `COMM` | `©cmt` | `comment` | Not imported |
| ISRC | `TSRC` | no explicit write in SpotDL 4.5.2 | `isrc` | Reader is not reliably format-aware |
| Popularity | `POPM` when nonzero | not written | not written | Not imported |
| Explicit flag | not written | `rtng` | not written | Not imported |
| Cover artwork | `APIC` | `covr` | FLAC picture / OGG picture block | Status is indexed; bytes are not compared with queued cover |
| Lyrics | `USLT`/`SYLT` | `©lyr` | `lyrics` | Not imported into Harmony |
| Spotify track ID | **not embedded** | **not embedded** | **not embedded** | Preserved through the job/source-link database relation |
| Spotify album ID | **not embedded** | **not embedded** | **not embedded** | Job has a field, but playlist mapping drops it |

WAV is recognized as a possible SpotDL output and SpotDL has a separate ID3
writer for it, but Harmony's general tag readers and explicit tag writer do not
list WAV among their supported formats. WMA and AAC can also pass the download
file filter while falling outside Harmony's declared tag-writing formats. These
formats should either be rejected at download configuration/preflight or added
to the tested metadata contract.

## Findings and risks

### High priority

#### H1 — No Harmony-owned canonical tag contract

Harmony validates only embedded title, artist, and duration. It does not verify
album, album artist, numbering, date, ISRC, URL, or artwork against the queued
Spotify snapshot. A SpotDL regression or metadata-search fallback can therefore
produce the correct recording with incomplete or inconsistent tags, which then
become the values used for the destination path and library row.

**Recommendation:** after identity validation and before import, write canonical
job metadata with an atomic backup/restore strategy, then re-read and verify it.
Preserve unrelated embedded tags when writing canonical download metadata.
Fail with a typed `tagging_failed` outcome when required identity/path fields
cannot be verified.

#### H2 — External identifiers are not round-tripped reliably

SpotDL writes MP3 ISRC as `TSRC`, while Harmony's generic reader requests
`tags.get("isrc")`; it also does not read `WOAS`. Spotify track/album IDs are not
written by SpotDL at all. Database source linking protects downloaded tracks
while the database is intact, but file-only rescans, restores, or moves cannot
reconstruct Spotify identity.

**Recommendation:** define format-specific canonical tags for ISRC, Spotify
track ID, Spotify album ID, and Spotify URL. Read both canonical and legacy
spellings/frames. Add round-trip tests and retain the database source link as a
second, not sole, identity store.

### Medium priority

#### M1 — Album resolution discards useful fields

Album jobs intentionally set ISRC to `None`, retain only a four-digit year, and
have no track/disc totals. This weakens duplicate matching before download and
makes a deterministic post-download tag contract impossible.

**Recommendation:** batch-fetch full track objects for album items (to obtain
external IDs), paginate albums larger than a single simplified-track page, and
extend `Track`/`DownloadJob` with release date, track total, and disc total.

#### M2 — Playlist mapping drops fields already returned by SpotDL

The SpotDL schema includes album ID, artist ID, all artists, and list metadata;
the mapper does not carry most of them into `Track`. This creates avoidable
differences among track, album, and playlist queue snapshots.

**Recommendation:** map album ID and artists immediately; support multiple
artist IDs if SpotDL exposes them; keep playlist position in the playlist/job
relation (not in audio tags).

#### M3 — Genre semantics are lossy and inconsistent

SpotDL writes only its first genre. Harmony can replace it with multiple genres,
but the library reader stores only the first easy-tag value in `Song.genre`, and
the source delimiter varies by format/player.

**Recommendation:** specify one canonical database representation and explicit
per-format serialization rules. Verify semantic values after writing rather
than requiring identical raw list representation.

#### M4 — Artwork is not validated as image data or canonical content here

SpotDL downloads cover bytes and labels them JPEG without checking the actual
content type. Harmony records a cover URL and detects whether artwork exists,
but the normal download path does not compare embedded bytes to a validated
cache or queued cover.

**Recommendation:** reuse `ArtworkService` validation/cache and the guarded
artwork-writing logic for downloads. Preserve non-front-cover images and verify
the final front cover hash.

### Low priority / maintainability

* `download_url()` is an unvalidated bulk-capable primitive. It is currently
  unused by the audited API; keep it private/remove it or make it obey the same
  one-track validation contract before future reuse.
* Spotify URL parsing accepts path prefixes and identifiers more loosely in
  `spotify_resource()` than the resolver's `_extract_id()`. Consolidate parsing
  so malformed or unsupported URLs receive one predictable clean response.
* The output filename is derived from provider-written tags before canonical
  reconciliation. Once H1 is implemented, build the destination only after the
  verified tag pass.

## Recommended implementation sequence

1. **Characterization tests:** generate tiny tagged fixtures for every allowed
   extension and assert the complete `read_metadata()` result.
2. **Reader corrections:** add `TSRC`, `WOAS`, MP4 freeform keys, and Vorbis
   aliases; prove round trips for external IDs and totals.
3. **Model completeness:** add release date and totals; retain album/artist IDs
   in album and playlist resolution; add migrations where persistence changes.
4. **Canonical download tagger:** write queued metadata atomically, preserve
   unrelated provider tags, validate artwork, and verify required fields.
5. **Pipeline integration:** run the tagger after audio identity validation and
   genre enrichment but before destination calculation/import; expose typed,
   non-sensitive failures in download history.
6. **End-to-end coverage:** exercise track, multi-disc album, playlist,
   collaboration, compilation, explicit, missing-ISRC, and fallback-search cases
   in MP3 plus the configured non-MP3 format.

## Acceptance criteria for a future metadata contract

For every successful Spotify track, album child, and playlist child job:

* title, artists, album, album artist, track/disc number and totals, full release
  date, ISRC when supplied, Spotify track/album IDs, Spotify URL, genre, and front
  cover round-trip from file tags;
* title, primary artist, duration, and version identity match before import;
* destination paths are built only from verified canonical tags;
* unavailable optional metadata is reported as absent, not as a failed audio
  download;
* a failed tag write restores the original staging file and never imports a
  partially modified file; and
* database identity links remain correct after a clean library rescan from the
  audio files alone.
