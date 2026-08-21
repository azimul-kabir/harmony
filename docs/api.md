# Library Jobs and Activity API

> v3.0.0 API guide. Interactive OpenAPI contracts are available at `/docs`
> while Harmony is running.

Library jobs extend Harmony's existing durable Task API. All timestamps are UTC
ISO-8601 values. Job responses include both the legacy progress keys
(`total`, `completed`, `progress`) and explicit job keys (`total_items`,
`successful_items`, `progress_percentage`) for additive compatibility.

## Health probes

- `GET /health` remains the compatibility liveness probe.
- `GET /health/live` returns process liveness and the Harmony version without
  querying dependencies.
- `GET /health/ready` verifies the database and Alembic marker plus readable,
  writable music, download, staging, failed-download, and artwork-cache
  directories. It returns HTTP 503 and bounded component reasons while any
  required dependency is unavailable.

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
- `GET /api/library/duplicates/{group_id}/resolution-preview?keep_song_id=...`
  revalidates the group and reports the exact removal set, reclaimable bytes,
  playlist impacts, warnings, and a short-lived confirmation token.
- `POST /api/library/duplicates/{group_id}/resolve` requires the preview's
  keeper, exact candidate/removal sets, token, and `confirm_delete=true`, then
  queues the removals through the durable Library bulk task.

Groups include stable Song IDs, evidence, confidence, quality attributes, and
a non-binding `recommended_keep_id`. Detection and preview are read-only.
Resolution deletes only the confirmed non-keeper audio files and retains their
Library records as missing provenance.

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
- `POST /api/sources` saves a Spotify or public YouTube Music playlist Source.
  The preferred request is `{ "source_url": "..." }`; the legacy
  `{ "spotify_url": "..." }` field remains accepted for compatibility.
  Harmony canonicalizes provider URLs and deduplicates on
  `(provider, external_id)`. Successful responses include `provider`,
  `external_id`, and `source_url`. Invalid, non-playlist, and unsupported URLs
  return HTTP 422 with `detail.code` and `detail.message` instead of an
  unhandled server error.
- `POST /api/sources/{source_id}/sync` starts an immediate background sync.
- `PATCH /api/sources/{source_id}` enables or disables a source.
- `PATCH /api/sources/{source_id}/auto-sync` saves
  `{ "enabled": true, "interval_minutes": 360 }`. The interval is bounded to
  15–10,080 minutes; the v2.0.0 UI offers hourly, 6-hour, 12-hour, daily, and
  weekly schedules.
- `GET /api/sources/stream` streams source, playlist, task, and schedule state.
  Source objects expose both the provider-neutral identity fields and the
  legacy `spotify_url` compatibility mirror.

## Playlist management

- `GET /api/playlists/{playlist_id}/tracks` returns source-ordered tracks,
  availability, artwork, and safe deletion eligibility.
- `POST /api/playlists/{playlist_id}/download` starts durable deletion of
  selected available Library files and refreshes affected M3Us.
- `DELETE /api/playlists/{playlist_id}` deletes the saved playlist and its
  generated M3U, not downloaded Songs or the associated Source.
- `GET /api/playlists/{playlist_id}/download` returns the generated M3U.
- `GET`, `POST`, and `DELETE /api/playlists/{playlist_id}/artwork` serve,
  atomically replace, or remove a Navidrome-compatible playlist sidecar image.
  Uploads accept JPEG, PNG, WebP, or GIF images up to 10 MB.
- `POST /api/tasks/jobs/clear` removes completed and cancelled Library activity.
  With `include_reviewed_attention=true`, it also removes reviewed terminal
  warnings; active and unreviewed attention jobs are always retained.
- Playlist acquisition goes through Sources or `POST /api/downloads`; v3 no
  longer exposes separate playlist import, comparison, and download endpoints.

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

Spotify failures may expose the stable reason code
`exact_match_unavailable` with the user-facing meaning **Exact match
unavailable**: Harmony could not obtain or validate the Spotify-linked track.
Harmony then tries controlled fallback searches, requiring the same primary
artist, a strongly related title, and a bounded duration difference. When ISRC
or album context is available, Harmony evaluates those targeted searches too
and ranks every safe result before selecting one. This outcome preserves the original
job identity for manual retry but is not automatically requeued indefinitely.
Other bounded provider categories include `provider_no_match`,
`provider_rate_limited`, `provider_unavailable`, and `provider_error`; an
unexpected multi-file response uses `unexpected_output_count`. API read models
must not expose provider stack traces, command arguments, credentials, cookies,
or local paths with these outcomes.

### `POST /api/downloads/bulk`

Transient provider failures are retried up to three total attempts when
`retry_failed` is enabled. Retry delays are persisted on each download job, so
workers remain available for other queued tracks while a retry is waiting. If
audio acquisition already succeeded, a post-processing retry reuses that file
only when it still exists beneath Harmony's configured staging directory.
Rate-limit failures use longer 60-second and 180-second delays and temporarily
postpone other queued jobs for the same source without blocking other sources.
Queued snapshot items expose `next_attempt_at`, `attempt`, and `max_attempts` for
retry countdowns. On startup, Harmony removes staging files older than seven
days unless they belong to active work or a recently failed resumable job.
The Downloads snapshot also includes aggregate-only `failure_reasons` entries
with a structured code, display label, and count for current failed jobs.

### `POST /api/downloads/{job_id}/manual-fallback`

Accepts `{ "url": "https://music.youtube.com/watch?v=..." }` only for a failed
matching or availability outcome. The URL must identify one track. Harmony
creates a separate queued job, preserving the failed history row and the
original Spotify metadata and playlist identity; the approved URL controls
audio acquisition only.

Safely updates a bounded set of Downloads records. The JSON request is `{ "action": "retry", "download_ids": [10, 11] }`; selected-ID requests accept at most 100 IDs. Allowed actions are `retry` (failed/cancelled only), `cancel` (queued/running only), `clear_history` (selected terminal records only), `clear_completed_history`, and `clear_failed_cancelled_history`. The final two actions intentionally operate only on terminal history and accept an empty ID list.

Responses contain aggregate-only fields: `action`, `requested`, `eligible`, `succeeded`, `skipped`, `failed`, and `result_code` (`completed`, `partial`, or `failed`). They never include source URLs, local paths, downloader/provider data, or task payloads. Clearing history never deletes downloaded files, Library records, or artwork cache; it cannot clear active or queued jobs. Pause and resume are not exposed because download-job pause/resume is not currently supported.

## Navidrome connection

- `POST /api/navidrome/test` calls authenticated Subsonic `ping`.
- `POST /api/navidrome/rescan` requests a bounded Navidrome library scan.
