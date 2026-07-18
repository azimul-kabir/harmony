# Changelog

All notable changes to Harmony are documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning**.

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
