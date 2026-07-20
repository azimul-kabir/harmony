# Harmony

<p align="center">
  <img src="docs/images/logo.png" alt="Harmony Logo" width="180">
</p>

<p align="center">
  <strong>Your Music. Your Way.</strong><br>
  A self-hosted music management platform that downloads, synchronizes, organizes, and manages your Spotify library for Navidrome and other media servers.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.4.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/docker-supported-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/platform-Synology%20NAS-success" alt="Synology">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

## Overview

Harmony is a modern self-hosted music management platform that bridges Spotify with your local music library.

It automatically downloads tracks, synchronizes playlists, organizes your collection, exports M3U playlists, and provides a beautiful web interface for browsing your music. Harmony acts as the **single source of truth** for your library while integrating seamlessly with media servers such as **Navidrome**, **Jellyfin**, and **Plex**.

Current Version: **v1.4.0**

---

# Features

## 🎵 Spotify Downloads

- Download tracks, albums, and playlists
- Multi-worker concurrent downloads
- Automatic retry support
- Live download progress
- Configurable audio quality (128 / 256 / 320 kbps)
- SpotDL integration
- Background download queue
- Automatic library import

---

## 🎼 Playlist Management

Harmony maintains Spotify playlists inside its own database.

Features include:

- Save Spotify playlists as Sources
- One-click synchronization
- Snapshot tracking
- Preserve playlist order
- Automatic duplicate detection
- Download only missing songs
- Automatic M3U generation
- Direct `.m3u` downloads from the web interface

---

## 📚 Modern Library Manager

Harmony now includes a complete library browser.

### Songs View

- Album artwork
- Artist
- Album
- Track selection
- Search
- Sorting
- Pagination

### Albums View

- Album artwork grid
- Track count
- Album duration
- Click to view album tracks

### Artists View

- Artist cards
- Song counts
- Album counts
- Click to browse artist collection

---

## 🔍 Powerful Library Search

Search instantly across:

- Song titles
- Artists
- Albums
- Genres
- Filenames

---

## ↕ Advanced Sorting

Sort your library by:

- Artist
- Song Name
- Album
- Newest Added
- Duration
- Year

---

## 📂 Automatic M3U Export

Harmony automatically exports playlists in standard `.m3u` format.

Compatible with:

- Navidrome
- Jellyfin
- Plex
- Kodi
- VLC
- Any M3U-compatible player

Features:

- Relative paths
- Unicode filenames
- Automatic regeneration
- Dedicated Playlists folder

---

## 🌍 Unicode Support

Harmony fully supports international filenames.

Playlists and music containing Bengali, Japanese, Arabic, Chinese, Korean, Cyrillic, Greek, Hindi, and many other languages are preserved correctly throughout the application.

---

## ⚙ Settings

Current configurable settings include:

- Download audio quality
- Storage paths
- Download engine
- Spotify configuration
- System information

Additional runtime settings are planned for future releases.

---

## 📱 Mobile Friendly

Harmony is designed for desktop and mobile devices.

Features include:

- Responsive layouts
- Touch-friendly controls
- Optimized album grids
- Responsive artist cards
- Mobile typography improvements
- Smooth scrolling
- Pagination optimized for smaller screens

---

# Download Pipeline

```text
Spotify
    │
    ▼
Fetch Metadata
    │
    ▼
Update Playlist Database
    │
    ▼
Generate M3U Playlists
    │
    ▼
Queue Missing Songs
    │
    ▼
Multi-worker Downloads
    │
    ▼
Staging Folder
    │
    ▼
Library Import
    │
    ▼
Rebuild Playlists
    │
    ▼
Navidrome / Jellyfin / Plex
```

---

# Technology Stack

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy
- SpotDL

### Frontend

- HTML5
- CSS3
- Vanilla JavaScript
- Server-Sent Events (SSE)

### Database

- SQLite

### Deployment

- Docker
- Docker Compose
- Synology NAS
- Linux
- macOS
- Windows

---

# Installation

Clone the repository.

```bash
git clone https://github.com/azimul-kabir/harmony.git
cd harmony
```

Create your local environment.

```bash
cp .env.example .env.local
```

Configure Spotify credentials.

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

Start Harmony.

```bash
docker compose up -d --build
```

Open:

```
http://localhost:8080
```

---

# Directory Structure

```text
Music/
├── Albums/
├── Singles/
├── Playlists/
│   ├── Chill Mix.m3u
│   ├── Road Trip.m3u
│   └── Workout.m3u
└── Harmony Database
```

---

# Why Harmony?

Harmony is more than a Spotify downloader.

It continuously synchronizes Spotify playlists, downloads only missing tracks, organizes your music collection, exports playlists, and provides a modern interface for browsing your entire library.

```text
Spotify
    │
    ▼
 Harmony
    ├── Playlist Database
    ├── Music Library
    ├── Library Manager
    └── M3U Export
             │
             ▼
 Navidrome / Jellyfin / Plex
```

No duplicate downloads.

No broken playlists.

No manual playlist maintenance.

Just a synchronized self-hosted music library.

---

# Roadmap

## v1.5

### Settings & Automation

- Editable application settings
- Scheduled synchronization
- Backup & restore
- Import/export settings

---

## v1.6

### Library Intelligence

- Library Health dashboard
- Metadata editor
- Duplicate finder
- Artwork manager
- Advanced search improvements

---

## v1.7

### Smart Library

- Favorites
- Ratings
- Tags
- Smart Playlists
- Collections

---

## Future

- Apple Music support
- YouTube Music support
- Deezer support
- Multiple music providers
- Multi-user support
- Plugin system
- REST API
- Progressive Web App (PWA)
- Lyrics support

---

# Screenshots

| Dashboard | Downloads |
|-----------|-----------|
| Coming Soon | Coming Soon |

| Sources | Playlists |
|----------|-----------|
| Coming Soon | Coming Soon |

| Library | Settings |
|----------|----------|
| Coming Soon | Coming Soon |

---

# Contributing

Contributions, bug reports, feature requests, and pull requests are always welcome.

If you have ideas to improve Harmony, feel free to open an issue or start a discussion.

---

# License

Harmony is licensed under the MIT License.

See the **LICENSE** file for details.

---

<p align="center">
Made with ❤️ for self-hosted music enthusiasts.
</p>
