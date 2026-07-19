# Changelog

All notable changes to Harmony are documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning**.

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

## Looking Ahead

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
