# Harmony - AI Agent Operational Guidelines

## Project Overview
Harmony is a self-hosted Spotify music downloader, playlist synchronizer, and library manager designed as a companion to Navidrome. It is the single source of truth for music acquisition, automatically exporting `.m3u` playlists and handling duplicate detection.

## Tech Stack & Rules
*   **Backend:** Python 3.12, FastAPI, Uvicorn.
*   **Database:** SQLite using SQLAlchemy 2.0 ORM and Alembic for migrations.
*   **Frontend:** HTML5, CSS3, and Vanilla JavaScript. **Do not use React, Vue, Tailwind, or any external frontend frameworks.**
*   **Real-time UI:** Server-Sent Events (SSE) via FastAPI `StreamingResponse`. 
*   **Core Engine:** SpotDL wrapper for downloading, Mutagen for metadata.
*   **Deployment:** Docker and Docker Compose (mobile-first, Synology NAS compatible).

## Architectural Constraints
1.  **Database Sessions:** Always use `SessionLocal()` and ensure the session is safely closed using `try/finally` blocks.
2.  **DOM Manipulation:** Use vanilla JavaScript for UI updates. Prefer surgical DOM patching (updating specific element IDs) over full page re-renders to prevent flickering during SSE streams.
3.  **UI/UX:** The interface is mobile-first. Use responsive flexbox/grid layouts. All artwork must be rendered as perfect 1:1 squares using `aspect-ratio: 1 / 1`.
4.  **Error Handling:** Fail gracefully. If a Spotify URL is invalid or an ISRC lookup fails, catch the error, log it via Loguru, and return a clean JSON response to the frontend.

## Current State
Harmony **v2.0.0** is the direct successor to the published v1.5.0 release.
It includes Metadata Intelligence, the Downloads Operations Center, direct
Navidrome playlist synchronization, playlist file management, auto-playlists,
per-source scheduled sync, runtime settings, and a mobile-first UI polish pass.
Harmony v1.6.0 was never published.
