# Changelog
All notable changes to Harmony will be documented in this file.

## v1.1.0 - 2026-07-18

This release drastically improves the frontend experience, transforming Harmony from a functional web dashboard into a highly polished, tactile, and native-feeling mobile web application.

### Added
- **Global Mini-Player:** Added a persistent, floating download bar tied to the SSE stream. Users can now navigate the entire app while keeping track of active download progress.
- **Floating Action Button (FAB) & Overlay:** Implemented a global quick-add button. Users can now queue new Spotify tracks, albums, or playlists from any page via a floating modal.
- **Worker Thread Visualization:** The Dashboard now exposes the active Python backend threads. Users can visually track what each concurrent worker is processing in real-time.
- **Skeleton Loaders:** Replaced static "Loading..." text with modern, pulsating placeholder blocks during data fetches for a smoother perceived load time.
- **Page Transitions:** Introduced a subtle 300ms fade-in animation to reduce visual jarring when navigating between application sections.

### Changed
- **Mobile-First Layouts:** Data tables on the Library, Downloads, and Settings pages now automatically transform into touch-friendly stacked cards on screens under 768px, completely eliminating horizontal scrolling.
- **Sticky Headers:** Search inputs and filter tabs are now pinned to the top of the viewport when scrolling, preserving user context on long lists.
- **Compact Command Center:** Shrunk the download input section spacing to maximize screen real estate for viewing the active queue on mobile devices.
- **Aesthetic Polish:** Replaced basic emojis with crisp, monochrome SVG icons and adjusted hardcoded text colors to ensure perfect contrast switching during OS Light/Dark mode toggles.

### Fixed
- Fixed an issue where long file paths, API keys, or unspaced song titles would break container boundaries and force horizontal scrolling on mobile.
- Fixed a CSS stacking context bug that caused floating UI elements (FAB, Mini-Player) to anchor to the bottom of the scrolling page instead of the viewport.
- Added padding offsets to ensure the floating action button no longer obscures the last item in scrolling lists.
- Fixed "ghost" skeleton loaders persisting on the Sources page after DOM patching.

## v1.0.0 - 2026-07-16
Initial Production Release
Harmony reaches its first stable release with a complete end-to-end download pipeline, playlist synchronization, multi-worker downloads, automated library organization, and a modern responsive web interface.

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
- Download only newly added tracks[cite: 1]
- Automatic duplicate detection[cite: 1]
- Task-based synchronization workflow[cite: 1]

#### Library
- Automatic folder organization[cite: 1]
- Album and Singles support[cite: 1]
- Duplicate detection[cite: 1]
- Metadata import[cite: 1]
- Library database management[cite: 1]
- Library rescan[cite: 1]
- Batch deletion[cite: 1]

#### Web Interface
- Dashboard[cite: 1]
- Downloads[cite: 1]
- Sources[cite: 1]
- Library[cite: 1]
- Settings[cite: 1]
- Responsive mobile interface[cite: 1]
- Desktop interface[cite: 1]
- Light Mode[cite: 1]
- Dark Mode[cite: 1]
- Automatic OS Theme Support[cite: 1]

#### Infrastructure
- Docker support[cite: 1]
- Synology NAS compatibility[cite: 1]
- SQLite database[cite: 1]
- Background workers[cite: 1]
- Task management[cite: 1]
- Download queue[cite: 1]
- Import pipeline[cite: 1]

### Changed
- Refactored download pipeline into independent services[cite: 1]
- Introduced dedicated SpotDL client wrapper[cite: 1]
- Improved playlist synchronization workflow[cite: 1]
- Improved task management architecture[cite: 1]
- Improved duplicate detection[cite: 1]
- Improved download reliability[cite: 1]
- Modernized project structure[cite: 1]
- Improved responsive UI across desktop and mobile devices[cite: 1]

### Performance
- Added configurable concurrent download workers[cite: 1]
- Faster playlist processing[cite: 1]
- Reduced duplicate checks[cite: 1]
- Improved queue throughput[cite: 1]
- Better background processing[cite: 1]

### Fixed
- Improved download stability[cite: 1]
- Improved playlist synchronization reliability[cite: 1]
- Improved metadata handling[cite: 1]
- Improved duplicate detection accuracy[cite: 1]
- Improved import consistency[cite: 1]

### Notes
Harmony v1.0.0 represents the first stable release of the project and establishes the core architecture for future development while maintaining backward compatibility[cite: 1].
