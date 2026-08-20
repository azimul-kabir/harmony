# ADR 0002: Provider-Neutral Download Boundary

- **Status:** Accepted
- **Release baseline:** v2.0.0

## Decision

Download requests retain an explicit source identity while durable queue and
Library workflows remain provider-neutral. Resolved Spotify tracks use bounded
direct yt-dlp candidate inspection and acquisition first; SpotDL remains the
acquisition fallback and is still required for unofficial Spotify playlist
metadata resolution. Public YouTube Music and explicit YouTube URLs use the
same yt-dlp infrastructure. Adapters normalize outcomes before persistence.

Spotify import is exact-match-only. Direct candidate metadata must satisfy the
same artist-credit, title, material-version, album-context, and duration rules
used by SpotDL output validation, plus an explicit confidence threshold. Only
one selected candidate is downloaded. If none is safe or yt-dlp fails, the
existing SpotDL attempt ladder runs as fallback and validates output as before.

## Consequences

- Provider URLs, credentials, command output, and raw extractor payloads are
  not exposed in UI read models.
- Provider failure does not weaken queue durability, cancellation, retry,
  telemetry, or outcome classification.
- No output or a rejected identity is a non-retryable
  `exact_match_unavailable` terminal attempt. Harmony retains the original
  source identity for a future manual retry but does not import or associate a
  substitute file.
- Playlist availability requires an available canonical Song association and
  an existing file. A completed job or predicted path is not availability.
- YouTube Music support does not imply authenticated catalogue access or bypass
  regional, age, removal, and rate restrictions.
- Adding another provider should implement the same normalized request and
  result boundary instead of branching Library or playlist services.
