# Changelog

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