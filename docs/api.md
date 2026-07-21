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
