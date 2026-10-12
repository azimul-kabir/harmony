# ADR 0001: Persistent Library Domain Model

- **Status:** Accepted
- **Release baseline:** v1.5.0; extended in v2.0.0

## Decision

Harmony's SQLite Library Index is the canonical application model for managed
music. Stable Song records own file identity, availability, descriptive and
technical metadata, external identifiers, provenance, artwork association, and
timestamps. Albums and Artists are indexed projections; playlists retain
ordered membership and source identity.

Filesystem scans reconcile the model but do not become the query layer.
Browsing, search, Library health, duplicate detection, playlist availability,
and bulk actions query the index. Harmony v3 removed the former analytics,
collection, and metadata-discovery surfaces; historical migration notes do
not imply those features remain active.

## Consequences

- A missing file does not immediately erase Song identity or audit history.
- Metadata lookup results are previews until explicitly selected and saved.
- The v3.1 metadata editor writes supported tags only after user confirmation.
- Navidrome consumes music and playlists but does not own Harmony's domain.
- Schema changes use Alembic and preserve upgrades from published releases.

See [Library architecture](../architecture/library.md) for the complete model.
