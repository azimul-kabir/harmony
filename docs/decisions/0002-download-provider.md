# ADR 0002: Provider-Neutral Download Boundary

- **Status:** Accepted
- **Release baseline:** v2.0.0

## Decision

Download requests retain an explicit source identity while durable queue and
Library workflows remain provider-neutral. Spotify acquisition uses SpotDL.
Opt-in public YouTube Music and explicit YouTube URLs use yt-dlp. Provider
adapters normalize metadata and outcomes before persistence.

## Consequences

- Provider URLs, credentials, command output, and raw extractor payloads are
  not exposed in UI read models.
- Provider failure does not weaken queue durability, cancellation, retry,
  telemetry, or outcome classification.
- YouTube Music support does not imply authenticated catalogue access or bypass
  regional, age, removal, and rate restrictions.
- Adding another provider should implement the same normalized request and
  result boundary instead of branching Library or playlist services.
