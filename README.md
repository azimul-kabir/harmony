# Harmony

<p align="center">
  <img src="docs/images/logo.png" alt="Harmony Logo" width="180">
</p>

<p align="center">
  <strong>A self-hosted Spotify music downloader, playlist synchronizer, and library manager.</strong><br>
  Download, organize, synchronize, and automatically manage your music collection with seamless integration for Navidrome and other media servers.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.3.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/docker-supported-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/platform-Synology%20NAS-success" alt="Synology">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

## Overview

Harmony is a modern self-hosted music management platform that automatically downloads music from Spotify, organizes your library, synchronizes playlists, and exports standard `.m3u` playlists for media servers such as **Navidrome**, **Jellyfin**, and **Plex**.

Unlike traditional downloaders, Harmony maintains its own playlist database and acts as the **single source of truth** between Spotify and your local music collection.

> **Current Version:** **v1.3.0**

---

# Features

## 🎵 Spotify Downloads

- Download Spotify tracks
- Download Spotify albums
- Download Spotify playlists
- Background download queue
- Multi-worker concurrent downloads
- Automatic retry support
- Live download progress
- SpotDL integration
- Download staging pipeline
- Automatic library import

---

## 🎚 Configurable Audio Quality (New in v1.3.0)

Harmony now allows selecting your preferred download quality directly from the Settings page.

Supported bitrates:

- 128 kbps
- 256 kbps
- 320 kbps

The selected quality is automatically passed to SpotDL for every download.

---

## 🎼 Native Playlist Management

Harmony stores Spotify playlists inside its own database.

Playlist information includes:

- Spotify Playlist ID
- Playlist name
- Track membership
- Playlist order
- Last synchronization
- Snapshot ID
- Export status

No duplicate music files are created.

---

## 🔄 Playlist Synchronization

Harmony automatically keeps your playlists synchronized.

Features include:

- Save Spotify playlists as Sources
- One-click synchronization
- Download only missing songs
- Preserve playlist order
- Automatic duplicate detection
- Snapshot ID tracking
- Incremental synchronization foundation

---

## 📂 Automatic M3U Export

Harmony automatically exports every playlist as a standard `.m3u` playlist.

Compatible with:

- Navidrome
- Jellyfin
- Plex
- Kodi
- VLC
- Any M3U-compatible player

Features include:

- Relative paths
- Automatic regeneration
- Real-time updates
- Dedicated `/Playlists` folder
- Unicode filename support

---

## 📥 Direct Playlist Download (New in v1.3.0)

Every playlist now includes a **Download .m3u** button.

Users can instantly download the generated playlist file directly from the browser without accessing the server filesystem.

---

## 🧠 Smart Library Matching

Harmony intelligently links historical downloads to Spotify tracks.

If a Spotify ID cannot be found, Harmony automatically searches using:

- Title
- Artist
- Album
- Existing metadata

Matched songs are permanently linked and immediately become part of their playlists.

---

## 📚 Library Management

Harmony automatically manages your music library.

Features include:

- Automatic organization
- Album & Singles folders
- Metadata import
- Duplicate detection
- Safe staging folder
- Library rescan
- Batch deletion
- Automatic playlist rebuilding

---

## 🌍 Unicode Support

Harmony fully supports international filenames.

Playlists and exported `.m3u` files correctly preserve characters from languages such as:

- Bengali
- Japanese
- Chinese
- Korean
- Arabic
- Cyrillic
- Greek
- Hindi

---

## ⚡ Modern Web Interface

### Dashboard

- Download statistics
- Active worker monitoring
- Queue overview
- System activity

### Downloads

- Live download queue
- Worker status
- Download progress
- Download history

### Sources

- Spotify playlist sources
- One-click synchronization
- Live synchronization status

### Playlists

- Playlist browser
- Playlist statistics
- Track counts
- Last synchronization
- Export status
- Download M3U button
- Mobile-friendly cards

### Library

- Browse downloaded music
- Search library
- Batch deletion
- Metadata overview

### Settings

- Storage paths
- Download engine
- Audio quality selection
- Spotify configuration
- Playlist settings
- System information

---

## 📱 Mobile First

Harmony is designed for both desktop and mobile devices.

Features include:

- Responsive layouts
- Mobile navigation
- Floating Quick Add button
- Persistent download status bar
- Touch-friendly controls
- Skeleton loading
- Automatic Light/Dark mode support

---

# Download Pipeline

```text
Spotify Playlist
        │
        ▼
Fetch Metadata
        │
        ▼
Update Playlist Database
        │
        ▼
Generate M3U Playlist
        │
        ▼
Queue Missing Downloads
        │
        ▼
Download Workers
        │
        ▼
Staging Folder
        │
        ▼
Library Import
        │
        ▼
Automatic Playlist Rebuild
        │
        ▼
Navidrome / Jellyfin / Plex
```

---

# Technology Stack

## Backend

- Python 3.12
- FastAPI
- SQLAlchemy
- SpotDL

## Frontend

- HTML5
- CSS3
- Vanilla JavaScript
- Server-Sent Events (SSE)

## Database

- SQLite

## Deployment

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

Copy the environment file.

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

Open your browser.

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
│   ├── Road Trip.m3u
│   ├── Chill Mix.m3u
│   └── Workout.m3u
└── Harmony Database
```

---

# Why Harmony?

Harmony is more than a Spotify downloader.

It continuously synchronizes Spotify playlists, automatically downloads missing tracks, manages your music library, and exports playlists for your favorite media server.

Harmony acts as the bridge between streaming services and your self-hosted music collection.

```text
Spotify
    │
    ▼
 Harmony
    │
    ├── Music Library
    ├── Playlist Database
    └── M3U Export
             │
             ▼
 Navidrome / Jellyfin / Plex
```

No duplicate music.

No manual playlist management.

No broken playlists.

Everything stays synchronized automatically.

---

# Roadmap

### v1.4

- Editable application settings
- Smart Library foundation
- Playlist automation
- Scheduled synchronization

### v1.5

- Smart Playlists
- Custom tags
- Favorites
- Ratings
- Notes

### v1.6

- Metadata editor
- Artwork manager
- Duplicate finder
- Library Health dashboard

### Future

- Apple Music support
- YouTube Music support
- Deezer support
- Multi-user support
- Plugin system
- REST API enhancements
- PWA support
- Lyrics
- Advanced search

---

# Screenshots

Coming soon.

---

# Contributing

Contributions are welcome!

If you have suggestions, ideas, or bug reports, feel free to open an issue or submit a pull request.

---

# License

Harmony is licensed under the MIT License.

See the `LICENSE` file for details.

---

<p align="center">
Built for self-hosted music enthusiasts.
</p>
