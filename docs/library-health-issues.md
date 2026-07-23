# Library Health issue details

## Issue-detail contract

`GET /api/library/health/issues/{check_id}` returns only **open, live** issues.  The
currently supported entity type is `song`; album and artist issue types are reserved
for future health rules and must supply equivalent identity before they are shown.
Every item contains a stable `entity_id`, human-readable `title`, `artist`, `album`,
track/disc numbers, availability, filename, problem field, detected value,
plain-language explanation, and recommended action. `id` is a diagnostic issue key,
not a user-facing song name.

Harmony intentionally exposes only `filename`, never an absolute host filesystem path.
This keeps Library Health useful when sharing screenshots without leaking NAS layout.

## Review navigation

Review links use `/library?song_id=<id>`. Missing records additionally use
`&include_missing=1`. The Library reads both values during initial load, includes
missing records when requested, focuses and scrolls the matching song row, and keeps
the URL intact for refresh and browser history. If the record is no longer in the
live result, the Library remains usable and the Health API does not advertise it as
an open issue on its next refresh.

## Discovery and correction

**Discover match** is analysis only: it must never download media, fetch artwork, or
mutate tags automatically. Harmony currently has no configured metadata-candidate
provider, so discovery reports `provider_unavailable` with a clear message and makes
no changes. When a provider is added, discovery must first return candidates and a
preview; applying metadata requires a separate explicit confirmation and must report
success or failure before the issue is refreshed.

The distinction is deliberate: health analysis identifies an issue; discovery finds
possible corrections; preview compares values; apply is the only mutating step.
