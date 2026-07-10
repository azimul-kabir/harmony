# Changelog

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