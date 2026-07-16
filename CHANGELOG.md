### `CHANGELOG.md` Update

```markdown
## v1.0.0 - 2026-07-16

### Added
- Complete UI Overhaul: Redesigned the frontend into a focused 5-section application (Dashboard, Downloads, Sources, Library, Settings).
- Real-Time Updates: Implemented Server-Sent Events (SSE) across the Dashboard, Downloads, and Sources pages for zero-latency UI updates without polling.
- SpotDL Fallback Mechanism: Added automatic plain-text search fallback with `--dont-filter-results` to bypass strict duration filtering when official Spotify URLs return a `LookupError`.
- Persistent SpotDL Cache: Added Docker volume mapping for SpotDL's internal cache to drastically reduce playlist scraping times.
- Granular Task Controls: Added Pause, Resume, and Cancel capabilities for active sync and download tasks directly from the UI.
- Library Maintenance Tools: Added debounced search, paginated views, batch deletion, and raw filename display for tracks missing ID3 metadata.
- Error Visibility: Surfaced raw SpotDL extraction errors directly to the frontend for transparent debugging.

### Changed
- Offloaded playlist syncing to FastAPI `BackgroundTasks`, eliminating UI freezing and API timeouts during 10+ minute scrapes.
- Updated SpotDL execution to use dynamic timeouts (20 minutes for full playlist scrapes, 5 minutes for individual track downloads).
- Refined internal queue logic to gracefully handle `LookupError` exceptions by failing over to secondary queries.

### Fixed
- Fixed issue where valid regional, progressive, or extended tracks were skipped due to duration mismatches on YouTube.
- Fixed a connection timeout bug where long playlist syncs caused the initial HTTP request to die.
- Restored missing `_fail_task` and `_complete_task` handlers in the task service to prevent worker crashes.

## v0.6.0 - 2026-07-10

### Added

- Spotify track downloads
- Spotify album downloads
- Background download worker
- Download queue
- Automatic duplicate detection
- Automatic library import
- Library scanner
- SQLite music database
- REST API
- Docker deployment
- Synology NAS support

### Improved

- Automatic music organization
- Metadata extraction
- Error handling
- Logging

### Known Issues

- Playlist downloads require a new metadata strategy due to Spotify Web API authentication changes.

## v0.5.0

### Added

- Intelligent playlist download service
- Playlist download API endpoint
- Smart playlist processing
- Prevention of downloading tracks already present in the local library
- Prevention of duplicate active download jobs
- Queue result domain models
- Per-track playlist download results
- Detailed playlist download summary
- Download exception hierarchy

### Changed

- Refactored download queue to return structured queue results
- Improved download queue architecture
- Extended playlist download response with per-track status
- Updated project documentation
- Improved Docker development environment

### Fixed

- Restored database persistence layer
- Fixed SQLite initialization
- Fixed worker recovery after restart
- Fixed duplicate download handling

---

## v0.4.0

### Added

- Spotify playlist import API
- Provider abstraction for music services
- SpotDL provider implementation
- Persistent download queue
- Background download worker
- Download job management API
- SQLite persistence for download jobs
- Automatic worker recovery after application restart
- Library scan API
- Smart download queue
- Prevention of duplicate active download jobs
- Prevention of downloading tracks already present in the local library
- Custom download exception handling

### Changed

- Refactored persistence layer into a dedicated `app/database` package
- Introduced SQLAlchemy declarative base and session management
- Improved Docker development environment with dedicated database, downloads and log volumes
- Updated project documentation and Quick Start guide
- Improved project structure and separation of concerns

### Fixed

- Restored missing database persistence layer
- Fixed database initialization
- Fixed download queue persistence across restarts
- Fixed library scanning and statistics endpoints

---

## v0.2.0

### Added

- Music library scanner
- Metadata extraction
- SQLite library database
- Library statistics endpoint
- Detection of new, updated and removed files
- Automated tests with pytest

### Changed

- Batch database writes during library scan
- Improved scan result reporting
- Repository cleanup
- Reduced Docker build context

---

## v0.1.0

### Added

- FastAPI application
- Docker support
- SQLAlchemy integration
- Initial project structure
