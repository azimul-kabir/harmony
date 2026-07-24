# Library Jobs and Activity API

> v2.0.0 API guide. Interactive OpenAPI contracts are available at `/docs`
> while Harmony is running.

Library jobs extend Harmony's existing durable Task API. All timestamps are UTC
ISO-8601 values. Job responses include both the legacy progress keys
(`total`, `completed`, `progress`) and explicit job keys (`total_items`,
`successful_items`, `progress_percentage`) for additive compatibility.

## Read jobs

- `GET /api/tasks/jobs/active` returns queued, running, and cancelling Library jobs.
- `GET /api/tasks/jobs/recent?limit=25` returns newest Library jobs in any state.
- `GET /api/tasks/jobs/{job_id}` returns one Library job.
- `GET /api/tasks/library-activity?limit=20` returns terminal Library activity.
- `GET /api/tasks/jobs/{job_id}/failures?offset=0&limit=50` returns newest-first,
  structured item failures. Offset is clamped to zero and limit to 1–100.

Job responses report `job_id`, `job_type`, `status`, timestamps, item counts,
derived processed/progress values, the current item, structured error summary,
cancellation time, initiator/source, resumability, and parsed recovery metadata.

Reviewed failures can be acknowledged without deleting their history:

- `POST /api/tasks/jobs/{job_id}/acknowledge`
- `POST /api/tasks/jobs/acknowledge` for a bounded job category

## Cancel a job

`POST /api/tasks/jobs/{job_id}/cancel` cancels queued work immediately. Running
work moves to `cancelling`; workers acknowledge cancellation between atomic item
operations and finish as `cancelled`. Repeating cancellation on terminal jobs is
safe.

Conflicting submissions return HTTP 409 with a `CONFLICTING_JOB` detail. Unknown
jobs return HTTP 404. Error payloads contain bounded user-safe codes/messages,
never raw tracebacks or authentication data.

## Navidrome status and scan controls

- `GET /api/navidrome/status` returns configuration, connectivity, scanner,
  last-scan, folder-count, and server-version state. An unavailable or
  unconfigured server is represented as a safe status payload so the dashboard
  can continue operating.
- `POST /api/navidrome/rescan?full_scan=false` requests an incremental scan.
- `POST /api/navidrome/rescan?full_scan=true` requests a full scan.

Harmony authenticates server-to-server using the Subsonic token flow. The
Navidrome password and generated authentication token are never returned to
the browser.

## Operation-specific compatibility APIs

- `POST /api/library/health/actions/{refresh|rebuild|verify|clear_artwork}`
- `GET /api/library/health/tasks/{job_id}`
- `POST /api/library/health/tasks/{job_id}/cancel`
- `POST /api/library/bulk`
- `GET /api/library/bulk/{job_id}`
- `POST /api/library/bulk/{job_id}/cancel`
- `GET /api/library/bulk/{job_id}/export`

These endpoints use the same persistent jobs and retain their existing response
fields. Bulk operations are `delete`, `move`, `rename`, `refresh_metadata`,
`refresh_artwork`, `fetch_artwork`, `forget_missing`, and `export`.

Duplicate intelligence is read-only:

- `GET /api/library/duplicates` returns paginated candidate groups. Optional
  `tier` values are `exact`, `strong`, `probable`, and `possible`; missing
  records are excluded unless `include_missing=true`.
- `GET /api/library/duplicates/{group_id}` returns one comparison group.

Groups include stable Song IDs, evidence, confidence, quality attributes, and
a non-binding `recommended_keep_id`. These endpoints never change Library rows
or audio files.

Manual artwork replacement uses multipart uploads:

- `POST /api/artwork/songs/{song_id}` accepts one `file` containing JPEG, PNG,
  or WebP data up to 15 MB and associates the validated content-addressed
  resource with the Song.
- `DELETE /api/artwork/songs/{song_id}` removes only the Song association.

Replacement and removal do not modify embedded audio-file artwork or delete
shared cached resources.

Advanced Library search remains available through `GET /api/library/search`.
The `q` value supports:

- field qualifiers: `title`, `artist`, `album`, `genre`, `playlist`,
  `filename`, `spotify`, `musicbrainz`, and `isrc`;
- quoted phrases, such as `title:"Northern Lights"`;
- exclusions, such as `artist:Aurora -genre:live`;
- intelligence filters: `has:issues`, `has:artwork`, `is:duplicate`,
  `is:missing`, `is:available`, `missing:artwork`, and `missing:metadata`.

Terms use AND semantics. Queries are bounded to 200 characters and 20 terms.
Unknown fields, unsupported filters, and unmatched quotes return HTTP 400.
Duplicate-only filtering is bounded to 800 candidate Songs so it remains
compatible with conservative SQLite parameter limits.

## Sources and automation

- `GET /api/sources` lists source state and schedule fields.
- `POST /api/sources` saves a Spotify source.
- `POST /api/sources/{source_id}/sync` starts an immediate background sync.
- `PATCH /api/sources/{source_id}` enables or disables a source.
- `PATCH /api/sources/{source_id}/auto-sync` saves
  `{ "enabled": true, "interval_minutes": 360 }`. The interval is bounded to
  15–10,080 minutes; the v2.0.0 UI offers hourly, 6-hour, 12-hour, daily, and
  weekly schedules.
- `GET /api/sources/stream` streams source, playlist, task, and schedule state.

- `GET /api/playlists/auto/definitions` lists built-in auto-playlist rules.
- `POST /api/playlists/auto/{rule_id}/generate` accepts
  `{ "limit": 50, "enabled": true }`. Supported v2.0.0 rules are
  `recently_added` and `recently_downloaded`; limits are bounded to 1–500.

## Playlist management

- `GET /api/playlists/{playlist_id}/tracks` returns source-ordered tracks,
  availability, artwork, and safe deletion eligibility.
- `POST /api/playlists/{playlist_id}/download` starts durable deletion of
  selected available Library files and refreshes affected M3Us.
- `DELETE /api/playlists/{playlist_id}` deletes the saved playlist and its
  generated M3U, not downloaded Songs or the associated Source.
- `GET /api/playlists/{playlist_id}/download` returns the generated M3U.
- `POST /api/playlists/import`, `/compare`, and `/download` retain the existing
  import, availability comparison, and direct-download contracts.

## Metadata Intelligence API

Metadata Intelligence uses the same durable Task lifecycle for discovery and
application work. The public discovery and application scope in v2.0.0 is
Songs; requests never silently apply provider values.

### Provider diagnostics

- `GET /api/providers/capabilities` lists MusicBrainz and Spotify metadata
  provider capabilities.
- `GET /api/providers/status` reports provider availability and cache-aware
  operational status.
- `POST /api/providers/test-search` and `POST /api/providers/lookup` provide
  bounded provider diagnostics. Spotify currently supports recording search
  and lookup only and returns `not_configured` when optional credentials are
  absent. Provider failures return a clean structured error response with a
  retryability flag.

### Health, discovery, and suggestions

- `GET /api/library/health/metadata/issues?status=open&included_only=true`
  returns only current included open metadata issue records. This is the
  Library Health Open-view scope and matches metadata score and summary totals.
  Omitting `included_only` preserves the broader audit-history list.

- `POST /api/metadata/discoveries/songs/{song_id}` starts discovery for one
  Song; `POST /api/metadata/discoveries/songs` accepts an explicit Song scope.
- `POST /api/metadata/discoveries/health-rules` and
  `POST /api/metadata/discoveries/health-issues` submit discovery from metadata
  health findings.
- `GET /api/metadata/discoveries` lists durable discovery records;
  `GET /api/metadata/discoveries/{discovery_id}` returns the selected candidate
  and explainable matching evidence.
- `POST /api/metadata/discoveries/{discovery_id}/select` explicitly selects a
  result. Ambiguous or low-confidence results require the corresponding
  confirmation flag. `DELETE /api/metadata/discoveries/{discovery_id}/selection`
  clears a selection.
- `POST /api/metadata/discoveries/{discovery_id}/suggestions` creates
  reviewable per-field suggestions from the selected candidate.
- `GET /api/metadata/suggestions/pending` lists suggestions; individual
  suggestion details, acceptance, and rejection are available at
  `/api/metadata/suggestions/{suggestion_id}` and its `/accept` and `/reject`
  actions.

### Application, history, and rollback

- `GET /api/library/songs/{song_id}/metadata` returns canonical values and
  review state. Song-scoped suggestion and history lists are available through
  `/metadata/suggestions` and `/metadata/history`.
- `POST /api/library/songs/{song_id}/metadata/manual-preview` normalizes and
  validates explicit operator edits without persistence.
  `POST /api/library/songs/{song_id}/metadata/manual-apply` queues changed,
  valid fields through the durable audit and rollback pipeline as provider
  `manual`; it never modifies audio files.
- `GET` or `POST /api/library/songs/{song_id}/metadata/application-preview`
  previews accepted or explicitly selected changes without writing them.
- `POST /api/library/songs/{song_id}/metadata/apply` queues accepted changes;
  `/apply-selected` queues an explicit suggestion selection. Batch submission
  is available at `POST /api/metadata/applications/apply`.
- `GET /api/metadata/batches`, `/api/metadata/batches/{batch_id}`, and
  `/api/metadata/batches/{batch_id}/results` expose durable application
  outcomes. `POST /api/metadata/batches/{batch_id}/rollback` queues reversible
  changes from a completed batch.
- `GET /api/metadata/history` lists audited changes. A single history entry can
  be previewed or rolled back at `/api/metadata/history/{history_id}` and its
  `/rollback-preview` and `/rollback` actions.

Use `GET /api/metadata/discoveries/capabilities` and
`GET /api/metadata/application/capabilities` to obtain the supported entity
types, fields, thresholds, and request limits before integrating a client.

Canonical metadata and file tags remain separate:

- `GET /api/library/songs/{song_id}/metadata/tag-preview` previews the file-tag
  mutation.
- `POST /api/library/songs/{song_id}/metadata/write-tags` explicitly writes one
  Song.
- `POST /api/library/metadata/write-tags` queues a bounded multi-Song write.

## Downloads queue snapshot

`GET /api/downloads/snapshot` returns the bounded read model used by the Downloads
Operations Center. `counts` contains separate `running`, `queued`, `paused`,
`completed`, `failed`, and `cancelled` totals. `active`, `queued`, and `paused`
lists are capped at 25 entries; the recent-history list is capped at 100.

Waiting entries are ordered exactly as the download worker claims them: oldest
`created_at`, then stable job ID. Running entries are ordered by `started_at`,
then ID. Queue positions are supplied only for this bounded waiting order.
The response intentionally excludes provider URLs, output paths, task payloads,
filesystem metadata, and raw errors. Active downloads include persisted
`progress`, `stage`, `heartbeat_at`, `worker`, `bytes_downloaded`,
`bytes_total`, `transfer_rate_bps`, and `eta_seconds`. Optional values are
`null` when the provider cannot measure them; clients must not infer missing
byte progress or ETA. Failed history filtering includes cancelled
jobs, matching the Dashboard attention link; `/downloads?status=cancelled`
remains available for cancelled-only history.

### `POST /api/downloads/bulk`

Safely updates a bounded set of Downloads records. The JSON request is `{ "action": "retry", "download_ids": [10, 11] }`; selected-ID requests accept at most 100 IDs. Allowed actions are `retry` (failed/cancelled only), `cancel` (queued/running only), `clear_history` (selected terminal records only), `clear_completed_history`, and `clear_failed_cancelled_history`. The final two actions intentionally operate only on terminal history and accept an empty ID list.

Responses contain aggregate-only fields: `action`, `requested`, `eligible`, `succeeded`, `skipped`, `failed`, and `result_code` (`completed`, `partial`, or `failed`). They never include source URLs, local paths, downloader/provider data, or task payloads. Clearing history never deletes downloaded files, Library records, or artwork cache; it cannot clear active or queued jobs. Pause and resume are not exposed because download-job pause/resume is not currently supported.
