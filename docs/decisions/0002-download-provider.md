# ADR 0002: Provider-Neutral Download Boundary

- **Status:** Accepted
- **Release baseline:** v2.0.0

## Decision

Download requests retain an explicit source identity while durable queue and
Library workflows remain provider-neutral. Spotify acquisition uses SpotDL.
Opt-in public YouTube Music and explicit YouTube URLs use yt-dlp. Provider
adapters normalize metadata and outcomes before persistence.

Spotify acquisition is exact-match-only. A track adapter invokes SpotDL once
with the original Spotify track URL; it must not generate an artist/title query
or pass `--dont-filter-results`. Success requires a zero exit status, exactly
one supported audio output, and agreement between the requested metadata and
the output's embedded primary artist, title, material version markers, and
reliable duration. This rule does not prohibit a user from explicitly choosing
the separate YouTube Music source.

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
