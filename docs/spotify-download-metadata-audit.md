# Spotify download and embedded-metadata audit

**Last updated:** 2026-10-12

**Audit scope:** Harmony's Spotify track, album, and playlist queue paths; the
direct yt-dlp acquisition path and SpotDL 4.5.2 fallback; download validation;
download-time tag mutation; import and indexing. This is a static code audit,
not a claim that every audio provider will return a playable match for every
Spotify item. The tag table below describes SpotDL fallback output only.

## Executive summary

All three supported Spotify URL types create durable per-track jobs and share
the same acquisition and validation path. Spotify jobs first inspect a bounded
set of yt-dlp candidates and download only the strongest candidate that passes
strict identity checks. When direct acquisition cannot produce a safe result,
the bounded SpotDL fallback runs and its output is validated before import.
Album and playlist jobs therefore do not bypass track-level validation.

Metadata embedding depends on the acquisition path. Direct yt-dlp acquisition
uses the resolved Harmony `Track` metadata; SpotDL fallback output is still
provider-owned. Spotify genre enrichment was removed in v3, so Harmony no
longer replaces file genres with Spotify-derived values. Harmony does not
reconcile every field in the queued track snapshot into SpotDL output.

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
2. Harmony resolves the Spotify track metadata and stores a durable job
   snapshot.
3. One durable job snapshots the resolved fields.
4. The worker inspects a bounded yt-dlp candidate search, validates candidates,
   and downloads only a safe match. If that path fails, it tries the bounded
   SpotDL fallback.
5. Harmony accepts exactly one audio file only after identity validation,
   imports it, indexes its embedded tags, and links the indexed song to the
   Spotify track ID in the database.

**Assessment:** the Web API response supplies the strongest queue context,
including ISRC and album ID. The direct path uses that resolved metadata to
inspect and tag its selected candidate. If SpotDL fallback is needed, Harmony
validates its output identity but does not rewrite every tag from the snapshot.

### Album

1. The API parses the URL as `album` and resolves the album through the Spotify
   Web API.
2. Harmony creates a task and one job for every not-owned/not-queued track.
3. Every child job follows the same validated single-track worker path.

**Assessment:** each child job uses the same direct-acquisition, fallback, and
identity-validation pipeline as a single track. Album metadata is resolved
before the child jobs are queued; optional-field fidelity still depends on the
upstream response and the selected acquisition path.

### Playlist

1. The API parses the URL as `playlist`.
2. Playlist metadata is obtained with `spotdl save`, including paging performed
   by SpotDL, then validated into Harmony models.
3. Harmony saves the database playlist, exports its M3U, and queues each
   not-owned track with its playlist position.
4. Every child job follows the same validated single-track worker path.

**Assessment:** each child job uses the same direct-acquisition, fallback, and
identity-validation pipeline as a single track. Playlist membership and order
remain database/M3U metadata rather than audio tags.

## SpotDL fallback tags

The following table describes SpotDL 4.5.2 fallback output. It does not
describe direct yt-dlp output. “SpotDL” means Harmony does not independently
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
| Genre | `TCON` | `©gen` | `genre` | Provider-written value is retained; Harmony no longer enriches genres from Spotify |
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

#### H1 — No Harmony-owned canonical tag contract for SpotDL fallback

Harmony validates embedded artist, title, material-version identity, and
reliable duration. It does not verify album, album artist, numbering, date,
ISRC, URL, or artwork in SpotDL fallback output against the queued Spotify
snapshot. A SpotDL regression can therefore produce the correct recording with
incomplete or inconsistent optional tags, which may affect the destination
path and Library row.

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

SpotDL fallback may write only its first genre, and the library reader stores
only the first easy-tag value in `Song.genre`; the source delimiter varies by
format/player. Harmony no longer enriches genres from Spotify or replaces
downloaded genre tags.

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
