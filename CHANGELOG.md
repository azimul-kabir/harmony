# Changelog

All notable changes to Harmony will be documented in this file.

---

# v1.0.0 - 2026-07-16

## 🎉 Initial Production Release

Harmony reaches its first stable release with a complete end-to-end download pipeline, playlist synchronization, multi-worker downloads, automated library organization, and a modern responsive web interface.

---

## Added

### Download Engine

- Spotify track downloads
- Spotify album downloads
- Spotify playlist downloads
- Multi-worker concurrent download engine
- Background download queue
- Download staging pipeline
- Automatic import engine
- SpotDL integration
- Configurable audio providers

### Playlist Synchronization

- Sync Sources
- One-click playlist synchronization
- Download only newly added tracks
- Automatic duplicate detection
- Task-based synchronization workflow

### Library

- Automatic folder organization
- Album and Singles support
- Duplicate detection
- Metadata import
- Library database management
- Library rescan
- Batch deletion

### Web Interface

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

### Infrastructure

- Docker support
- Synology NAS compatibility
- SQLite database
- Background workers
- Task management
- Download queue
- Import pipeline

---

## Changed

- Refactored download pipeline into independent services
- Introduced dedicated SpotDL client wrapper
- Improved playlist synchronization workflow
- Improved task management architecture
- Improved duplicate detection
- Improved download reliability
- Modernized project structure
- Improved responsive UI across desktop and mobile devices

---

## Performance

- Added configurable concurrent download workers
- Faster playlist processing
- Reduced duplicate checks
- Improved queue throughput
- Better background processing

---

## Fixed

- Improved download stability
- Improved playlist synchronization reliability
- Improved metadata handling
- Improved duplicate detection accuracy
- Improved import consistency

---

## Notes

Harmony v1.0.0 represents the first stable release of the project and establishes the core architecture for future development while maintaining backward compatibility.
