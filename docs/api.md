# Library Jobs and Activity API

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
`refresh_artwork`, and `export`.

## Metadata Intelligence API

Metadata Intelligence uses the same durable Task lifecycle for discovery and
application work. The public discovery and application scope in v1.6.0 is
Songs; requests never silently apply provider values.

### Provider diagnostics

- `GET /api/providers/capabilities` lists configured metadata provider
  capabilities.
- `GET /api/providers/status` reports provider availability and cache-aware
  operational status.
- `POST /api/providers/test-search` and `POST /api/providers/lookup` provide
  bounded MusicBrainz diagnostics. Provider failures return a clean structured
  error response with a retryability flag.

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
