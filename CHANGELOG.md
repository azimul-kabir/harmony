# Changelog

All notable changes to Harmony are documented in this file. The format is based
on **Keep a Changelog**, and this project follows **Semantic Versioning**.

## [Unreleased]

### Added

- Playlist cover upload, preview, replacement, and removal using
  Navidrome-compatible sidecar images beside exported M3U files.

### Fixed

- Library hero controls now use consistent typography and sizing on desktop,
  and remain on-canvas as a full-width action row on mobile.
- Duplicate candidate file details now use labeled, evenly aligned statistics
  with a full-width keeper choice on small screens.

### Planned

- Additional media-server API integrations beyond Navidrome.
- Duplicate detection and user-defined smart-playlist rules.

---

## [v2.0.0] - 2026-07-24

Harmony v2.0.0 is the direct successor to v1.5.0. Harmony v1.6.0 was never
published; documentation that previously assigned Metadata Intelligence to
v1.6.0 described unreleased development work. This release combines that work
with the Downloads Operations Center, Navidrome playlist synchronization,
playlist file management, automation, and a comprehensive responsive UI pass.

### Added

- **Metadata Health Engine:** Added durable, provider-neutral health rules for
  missing, inconsistent, and malformed metadata, with severity, evidence,
  status, and safe repair guidance exposed in the Library Health experience.
- **MusicBrainz Provider Foundation:** Added rate-limited, retry-aware,
  normalized MusicBrainz search and lookup infrastructure with bounded local
  caching, provider diagnostics, and configurable timeout, retry, concurrency,
  request-rate, and cache-TTL settings.
- **Explainable Metadata Discovery:** Added durable Song discovery jobs that
  generate bounded search variants, rank candidates deterministically, retain
  positive/conflicting/unavailable evidence, identify ambiguity, and require
  explicit confirmation for ambiguous or low-confidence selections.
- **Reviewable Suggestions:** Added per-field metadata suggestions with
  confidence, provider provenance, match evidence, review state, and stale
  canonical-value detection before a change can be applied.
- **Safe Metadata Application:** Added previews and durable background batches
  for accepted or selected Song suggestions, including per-Song reservations,
  stale-value protection, force-confirmation controls, progress reporting, and
  structured outcomes.
- **Audit and Rollback:** Added metadata history, batch result views, and
  reversible rollback previews/actions so each applied field change has an
  accountable provenance trail.
- **Metadata APIs:** Added provider diagnostics, discovery, candidate
  comparison/selection, suggestion review, application, history, batch, and
  rollback endpoints. Interactive contracts are available at `/docs`.
- **Downloads Operations Center:** Added deterministic queue snapshots,
  persisted history, telemetry, outcome classification, job details, bulk
  retry/cancel/history actions, and safer cancellation and redownload behavior.
- **YouTube Music Source:** Added opt-in public YouTube Music and explicit
  YouTube URL downloads through yt-dlp, with normalized diagnostics and no
  cookie or authenticated-scraper requirement.
- **Navidrome Controls:** Added safe status and scan APIs plus direct,
  order-preserving playlist synchronization through the Subsonic API.
  Ambiguous, read-only, and failed updates fall back to targeted M3U import.
- **Playlist Management:** Added availability summaries, filtering, Spotify
  links, one-click resync, M3U downloads, ordered Library file management,
  durable selected-file deletion, artwork, and safe saved-playlist deletion.
- **Auto-playlists:** Added bounded Recently Added and Recently Downloaded
  playlist generation with a configurable 1–500-song limit.
- **Scheduled Sources:** Added per-source auto-sync with hourly, 6-hour,
  12-hour, daily, and weekly intervals.
- **Library Job Review:** Added complete failure diagnostics and durable
  acknowledgement of historical job warnings without deleting audit history.
- **Runtime Settings:** Added editable application settings and reorganized
  mobile Settings navigation.

### Changed

- Extended the Library Index with MusicBrainz release, release-group, artist,
  release-artist, release-date, original-release-date, track-total,
  disc-total, and compilation metadata needed for canonical comparisons.
- Moved long-running metadata discovery and application work onto Harmony's
  persistent task lifecycle, including durable cancellation and recovery data.
- Updated Docker dependency installation to use the canonical `pyproject.toml`
  manifest with cached build stages.
- Made playlist export targeted and atomic, preserved source position, and
  excluded missing files from generated M3Us.
- Added explicit canonical audio-tag writing and optional embedding of cached
  artwork after a separate user confirmation.
- Redesigned mobile navigation and polished Dashboard, Downloads, Sources,
  Library, Settings, overlays, dialogs, tabs, pagination, action rows, focus
  behavior, and accessibility.

### Fixed

- Repaired interrupted and legacy metadata schema upgrades and missing Song
  columns without discarding existing data.
- Prevented completed downloads from regenerating unrelated playlists.
- Reconciled playlist imports during incremental scans and corrected stale
  metadata projections.
- Fixed canonical MusicBrainz release artwork lookup and YouTube Music
  thumbnail post-processing.
- Fixed Downloads outcome serialization, queue history, hidden recovery
  actions, and failed/cancelled filtering.
- Fixed mobile overflow, scrolling, dense control spacing, and auto-sync
  dropdown resets caused by live source-card refreshes.

### Upgrade

- This direct v1.5.0 upgrade includes Alembic revisions `20260721_0009` through
  `20260724_0025`. They add metadata intelligence, health, provider cache,
  matching/application state, genre provenance, download outcomes and
  telemetry, playlist metadata and Navidrome IDs, Library-job review state,
  auto-playlists, and source scheduling.
- Back up the persistent SQLite database before deploying. Start Harmony
  normally after deployment; Alembic applies the migrations automatically.
- Review `.env.example` for MusicBrainz, Navidrome, Spotify genre enrichment,
  and YouTube Music settings.

### Documentation

- Reconciled README, roadmap, API, architecture, configuration, and release
  documents around the actual v1.5.0 → v2.0.0 release path.
- Added dedicated v2.0.0 release notes with deployment and validation steps.

---

## [v1.5.0] - 2026-07-21

Harmony v1.5.0 establishes the Library Foundation as the canonical index for
managed music and adds the management, observability, and scalability layers
built on top of it. Playback remains delegated to compatible media servers;
direct Navidrome integration remains future work.

### Added

- **Persistent Library Index:** Stores file identity, descriptive and technical
  metadata, external identifiers, download provenance, artwork state, file
  availability, and indexing timestamps while preserving stable internal Song
  IDs across moves and missing files.
- **Incremental Filesystem Watcher:** Detects new, modified, deleted, moved, and
  renamed audio files through native filesystem events without periodic full
  rescans. Includes debounce, retry, supervision, and Library SSE events.
- **Indexed Search:** Added an SQLite FTS5 projection covering title, artist,
  album, genre, playlist, filename, Spotify ID, MusicBrainz ID, and ISRC. Search
  never reads the filesystem.
- **Library Views:** Added Songs, Albums, Artists, and Smart Collections views
  backed by the Library Index, including responsive artwork cards and counts.
- **Sorting and Filtering:** Added composable filters for artist, album, genre,
  codec, bitrate, date added, missing artwork, and missing metadata, plus stable
  sorting by artist, album, title, date, bitrate, duration, and year. Browser
  preferences persist locally.
- **Smart Collections:** Added automatic Recently Added, Recently Downloaded,
  Highest Bitrate, Missing Artwork, Missing Metadata, Recently Modified, and
  Large Albums collections. Favorites remains an explicit placeholder.
- **Artwork Foundation:** Detects embedded and folder artwork, stores unique
  images in a content-addressed local cache, and exposes reusable artwork APIs.
  Remote artwork downloads and manual replacement remain future work.
- **Library Analytics:** Added indexed aggregates for songs, albums, artists,
  genres, storage, average bitrate and duration, album insights, and recently
  added music.
- **Bulk Operations:** Added asynchronous multi-song delete, move, pattern-based
  rename, metadata refresh, artwork refresh, and ZIP export with confirmations,
  durable progress, cancellation, and per-song failure reporting.
- **Library Health Dashboard:** Added a health score, completeness checks,
  storage and update metrics, and task-backed Refresh Library, Rebuild Index,
  Verify Files, and Clear Artwork Cache actions. Duplicate detection is shown as
  an unavailable placeholder until its engine is implemented.
- **Typed Library APIs:** Added documented OpenAPI response contracts for Song,
  search, health, bulk-task, album, and artist read models. API documentation is
  available at `/docs` while Harmony is running.

### Changed

- Consolidated Song serialization, playlist provenance, Library predicates,
  task progress, timestamp handling, and keyset pagination into reusable
  services instead of duplicating logic across APIs and workers.
- Clarified canonical Library service boundaries and compatibility facades in
  `docs/architecture/library.md`.
- Standardized UTC storage using naive UTC values compatible with the existing
  SQLite schema.
- Added optional bounded pagination to Library list APIs while retaining
  existing client-compatible defaults.

### Fixed

- Backfilled legacy `songs.created_at` values during migration and made Library
  Song serialization resilient while an upgrade is pending. This prevents
  legacy rows with missing creation timestamps from invalidating Song API
  responses.

### Performance

- Replaced the N+1 FTS rebuild with a set-based `INSERT ... SELECT` projection
  and pre-aggregated playlist names.
- Added SQLite-safe batching for incremental search projection updates.
- Streamed scan reconciliation rows instead of materializing the complete Song
  table as ORM objects.
- Added keyset iteration for verification and artwork-cache maintenance.
- Eager-loaded artwork and batched playlist provenance to eliminate Library API
  serialization N+1 queries.
- Reduced artwork folder scanning to a fixed candidate set.
- Added a regression test proving a 2,500-Song FTS rebuild uses a constant
  number of SQL statements.

### Documentation

- Expanded the Library architecture document with canonical domain ownership,
  search, watcher, artwork, collections, analytics, bulk operations, health,
  API contracts, large-library policies, and future integration boundaries for
  MusicBrainz, YouTube Music, duplicate detection, metadata repair, and
  Navidrome.

---

## [v1.4.0] - 2026-07-20

This release significantly enhances Harmony's Library, transforming it into a modern music collection manager with multiple browsing modes, advanced search, flexible sorting, and an improved mobile experience.

### Added

- **Multiple Library Views:** Added **Songs**, **Albums**, and **Artists** tabs for browsing the library in different ways.
- **Album View:** Introduced a visual album grid with artwork, track counts, durations, and click-to-filter functionality.
- **Artist View:** Added artist cards displaying song and album counts with click-to-filter support.
- **Advanced Sorting:** Added sorting by Artist, Song Name, Album, Newest Added, Duration, and Year.
- **Unified Library Search:** Enhanced search to match song titles, artists, albums, genres, and filenames.
- **Tab-Aware Pagination:** Added dedicated pagination for Songs, Albums, and Artists views for improved performance with large libraries.

### Changed

- **Responsive Layouts:** Redesigned library grids for improved desktop and mobile browsing.
- **Mobile UI:** Improved typography and multi-line text wrapping for long artist and album names.
- **Library Navigation:** Enhanced view switching while preserving search, sorting, and pagination state.

### Performance

- Optimized library rendering for smoother scrolling and faster page updates.
- Improved pagination performance and reduced browser memory usage for large music collections.

---

## [v1.3.0] - 2026-07-19

This release focuses on usability, reliability, and playlist management improvements. Harmony introduces configurable audio quality, direct playlist downloads, improved Unicode support, and numerous backend refinements for a smoother synchronization experience.

### ✨ Added

- **Audio Quality Control**
  - Added a configurable audio quality setting in **Settings → Downloads**.
  - Users can now choose their preferred download bitrate:
    - 128 kbps
    - 256 kbps
    - 320 kbps
  - Harmony automatically passes the selected bitrate to SpotDL during downloads.

- **Direct M3U Download**
  - Added a **Download .m3u** button to every playlist card.
  - Users can instantly download the generated playlist file directly from the browser.
  - Added a dedicated API endpoint for serving exported playlist files.

- **Improved Unicode Support**
  - Playlist filenames now preserve Unicode characters instead of aggressively sanitizing names.
  - Playlists containing Bengali, Japanese, Arabic, Chinese, and other non-Latin characters now display correctly in Navidrome and other compatible media servers.

- **Improved Timezone Handling**
  - Added robust client-side fallback logic for date and time formatting.
  - Synchronization timestamps now display correctly even when browser timezone data is unavailable or delayed.

---

### 🔄 Changed

- **Database Reliability**
  - Updated the database session configuration to use absolute filesystem paths.
  - Prevents accidental database recreation or data loss after Docker container restarts.

- **Efficient UI Updates**
  - Replaced full list re-rendering with a surgical DOM patching approach.
  - Only modified playlist cards are updated, resulting in smoother real-time synchronization and reduced UI flicker.

- **Playlist Filename Sanitization**
  - Simplified filename sanitization to remove only operating system restricted characters.
  - Language-specific characters are now preserved for cleaner playlist names.

---

### 🐛 Fixed

- Fixed a `NameError` in the Playlist API caused by a missing playlist database model import.
- Fixed an `IndentationError` in the playlist export logic that prevented M3U generation.
- Fixed browser caching issues by versioning static JavaScript and CSS assets.
- Improved playlist export reliability for libraries containing international filenames.
- Fixed inconsistent timestamp rendering across browsers.

---

### ⚡ Performance

- Faster playlist synchronization through incremental DOM updates.
- Reduced unnecessary frontend rendering during Server-Sent Events (SSE).
- Improved M3U generation performance and filename handling.
- More reliable database initialization inside Docker environments.

---

### 🛠 Developer Improvements

- Refactored playlist export logic for improved maintainability.
- Improved database initialization and path resolution.
- Cleaner frontend update architecture for future playlist enhancements.
- Better cache management during frontend deployments.

---

## Upgrade Notes

After upgrading to **v1.3.0**:

- Hard refresh your browser (or clear the browser cache) to load the latest JavaScript and CSS assets.
- Existing playlists will continue to function without migration.
- Audio Quality defaults to the previous behavior until changed in **Settings → Downloads**.

---

## Looking Ahead (as documented in v1.3.0)

The improvements in v1.3.0 provide the foundation for upcoming releases, including:

- Editable application settings
- Smart Library
- Smart Playlists
- Scheduled synchronization
- Advanced library management
- Metadata editing
- Enhanced Navidrome integration

---

## v1.2.0 - 2026-07-19
This release introduces a major architectural shift, making Harmony the single source of truth for your playlists. It natively bridges the gap with Navidrome (and other media servers) through fully automated `.m3u` playlist generation.

### Added
- **Native Playlist Database:** Harmony now natively tracks Spotify playlists and track positions in the database without duplicating audio files.
- **Automatic M3U Export:** Playlists are instantly exported as standard `.m3u` files using relative paths to a dedicated `/Playlists` folder. Navidrome, Plex, and Jellyfin can now automatically mirror Harmony's playlists.
- **Playlists UI:** Added a new dedicated "Playlists" tab to the sidebar. Users can view synced playlists, track counts, last sync timestamps, and M3U export statuses as mobile-friendly cards.
- **Self-Healing Indexer:** Added a text-based fallback matcher. Historic tracks downloaded before Harmony's database existed are now automatically identified by Title/Artist, added to the `.m3u` file, and permanently linked to their Spotify IDs.
- **Snapshot ID Tracking:** Harmony now stores the Spotify `snapshot_id` to prepare for future delta-sync optimizations, heavily reducing API calls.

### Changed
- **Sync Source Workflow:** Playlist synchronization now updates the internal database and writes the `.m3u` file *before* queuing missing tracks, ensuring the playlist file exists immediately.
- **Real-Time Playlist Updates:** Download workers now trigger an automatic M3U rebuild the exact second a missing track finishes downloading. Your Navidrome playlists will update in real-time as the queue processes. 
- **Navigation:** Inserted the Playlists UI tab seamlessly between the "Sources" and "Library" tabs on both desktop and mobile layouts.

---

## [1.1.0] - 2026-07-18

### Added

- Added a persistent floating **Download Status Bar** that remains visible across all pages and displays real-time download progress.
- Added a global **Quick Add** floating action button (FAB) for instantly queueing Spotify tracks, albums, and playlists from anywhere in the application.
- Added a global download modal accessible from every page.
- Added real-time visualization of active download workers on the Dashboard.
- Added skeleton loading animations to improve perceived loading performance.
- Added subtle page transition animations for smoother navigation.
- Added responsive mobile card layouts for Library, Downloads, and Settings pages.
- Added sticky search bars and filter headers for improved navigation on long pages.
- Added bottom spacing to scrolling views to prevent floating controls from covering content.

### Changed

- Redesigned the interface with a mobile-first approach.
- Converted desktop-style tables into touch-friendly responsive cards on smaller screens.
- Reduced spacing in the Dashboard command center to maximize available screen space.
- Improved overall responsiveness across mobile and desktop devices.
- Replaced emoji icons with clean monochrome SVG icons.
- Improved typography, spacing, and visual hierarchy throughout the application.
- Enhanced automatic Light and Dark Mode appearance.
- Improved color contrast for better accessibility.

### Fixed

- Fixed horizontal scrolling caused by long filenames, API keys, and unbroken text.
- Fixed floating UI elements incorrectly positioning relative to scrolling containers.
- Fixed floating action button overlapping the final items in scrolling lists.
- Fixed skeleton loaders occasionally remaining visible after page updates.
- Fixed various responsive layout inconsistencies across mobile devices.
- Improved stability of live UI updates from Server-Sent Events (SSE).

### Performance

- Improved perceived loading speed through skeleton loaders.
- Reduced unnecessary layout reflows during navigation.
- Improved responsiveness while monitoring concurrent downloads.
- Optimized scrolling performance on mobile devices.
- Smoothed page transitions throughout the application.

---

## [1.0.0] - 2026-07-16

### Added

#### Download Engine

- Spotify track downloads
- Spotify album downloads
- Spotify playlist downloads
- Multi-worker concurrent download engine
- Background download queue
- Download staging pipeline
- Automatic import engine
- SpotDL integration
- Configurable audio providers

#### Playlist Synchronization

- Sync Sources
- One-click playlist synchronization
- Download only newly added tracks
- Automatic duplicate detection
- Task-based synchronization workflow

#### Library

- Automatic folder organization
- Album and Singles support
- Duplicate detection
- Metadata import
- Library database management
- Library rescan
- Batch deletion

#### Web Interface

- Dashboard
- Downloads
- Sources
- Library
- Settings
- Responsive mobile interface
- Desktop interface
- Light Mode
- Dark Mode
- Automatic OS Theme Support

#### Infrastructure

- Docker support
- Synology NAS compatibility
- SQLite database
- Background workers
- Task management
- Download queue
- Import pipeline

### Changed

- Refactored the download pipeline into independent services.
- Introduced a dedicated SpotDL client wrapper.
- Improved playlist synchronization workflow.
- Improved task management architecture.
- Improved duplicate detection.
- Improved download reliability.
- Modernized the project structure.
- Enhanced responsive UI across desktop and mobile devices.

### Performance

- Added configurable concurrent download workers.
- Faster playlist processing.
- Reduced duplicate checks.
- Improved queue throughput.
- Better background processing.

### Fixed

- Improved download stability.
- Improved playlist synchronization reliability.
- Improved metadata handling.
- Improved duplicate detection accuracy.
- Improved import consistency.

### Notes

Harmony v1.0.0 represents the first stable release of the project, establishing the foundation for future development while maintaining a reliable and scalable architecture.
