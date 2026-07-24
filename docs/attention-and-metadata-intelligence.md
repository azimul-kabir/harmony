# Dashboard attention and metadata intelligence

> v2.0.0 operational contract

## Attention-item contract

`GET /api/dashboard` and the dashboard SSE stream publish one `attention` snapshot. `items` contains only non-zero, actionable categories; `total_count` and severity counts are sums of those item counts. `healthy`, `headline`, and `message` are derived from that exact list, so a healthy message is possible only when the list is empty.

| Category | Unit | Included | Excluded |
| --- | --- | --- | --- |
| Failed downloads | download records | `failed` | cancelled, queued, running, completed, skipped |
| Missing library files | song records | `availability_status=missing` | available records |
| Maintenance jobs | jobs | `failed`, `completed_with_errors`, `interrupted` | queued, running, paused, cancelling, completed, cancelled |
| Bulk jobs | jobs | `failed`, `completed_with_errors`, `interrupted` | queued, running, paused, cancelling, completed, cancelled |
| Open metadata issues | included current issue records | `open` and current entity scope | ignored, resolved, stale, and missing-file song records |

Library-job attention can be acknowledged per job or by category. Review state
suppresses the warning while preserving job summaries and safe per-item failure
diagnostics for audit and troubleshooting.

The dashboard does not serialize filenames, paths, error details, or task payloads. Cancelled jobs and completed history are intentionally not attention items. Retryable failed downloads and jobs are included.

## Metadata issue scope and score

Metadata counts use **included open issue records**: `status=open`, with song issues limited to currently available songs. Album and artist projection keys are respectively normalized album-artist/title and normalized artist names; full analysis resolves open projection issues whose current key no longer exists. Resolved and ignored records are retained as historical diagnostics; ignored records are reported separately and neither status affects severity totals or score. A reappearing entity is reconciled normally and can reopen an equivalent resolved finding.

The severity and “most frequent” summaries use this same included-record population. They label counts as issue records, avoiding confusion with rule types or affected library entities. The score uses weights info 0.25, warning 2, error 6, critical 12, caps the aggregate penalty per entity at 20, and divides by a budget of 10 per available song. A non-zero penalty is floored so an included warning cannot display as 100/100.

The Library Health default Open view requests `included_only=true`, so its pagination total is the same included-record population used by the score and summary. The API retains its broader historical list by default; callers can omit `included_only` to inspect resolved, ignored, or otherwise excluded audit records. Entity renames are identity changes because their normalized projection keys change; the old projection is resolved and the new projection is analyzed.
