# Harmony

<p align="center">
  <img src="docs/images/logo.png" alt="Harmony Logo" width="160">
</p>

<p align="center">
  <strong>A self-hosted Spotify music downloader, playlist synchronizer, and library manager.</strong><br>
  Automatically download, organize, synchronize, and export your music library for Navidrome and other media servers.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.2.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/docker-supported-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/platform-Synology%20NAS-success" alt="Synology">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

Harmony is a self-hosted music downloader and library manager that automatically downloads, organizes, synchronizes, and maintains your Spotify music collection.

Built with **FastAPI**, **Docker**, **SpotDL**, and **SQLite**, Harmony is designed for home servers and NAS devices. It now serves as the **single source of truth** for your playlists, automatically generating standard `.m3u` playlists compatible with **Navidrome**, **Plex**, **Jellyfin**, and other media servers.

> **Current Version:** **v1.2.0**

---

# Features

## Spotify Downloads

- Download Spotify tracks
- Download Spotify albums
- Download Spotify playlists
- Multi-worker concurrent downloads
- Background download queue
- Automatic retry support
- Download staging pipeline
- SpotDL integration
- Live download progress
- Queue management

---

## Playlist Synchronization

Harmony keeps your Spotify playlists synchronized locally while preserving playlist membership and ordering.

### Features

- Save Spotify playlists as Sync Sources
- One-click playlist synchronization
- Detect newly added tracks
- Download only missing songs
- Skip existing library content
- Preserve Spotify playlist order
- Automatic duplicate detection
- Snapshot ID tracking for efficient future synchronizations

---

## Native Playlist Management

Harmony now maintains its own playlist database.

Unlike traditional downloaders, Harmony remembers which songs belong to which playlists without duplicating music files.

### Features

- Native playlist database
- Track playlist membership
- Preserve Spotify ordering
- Track last synchronization time
- Real-time playlist updates
- Playlist statistics
- Playlist browser
- Automatic playlist rebuilding

---

## Automatic M3U Export

Harmony automatically exports every synchronized playlist as a standard `.m3u` playlist.

Compatible with:

- Navidrome
- Jellyfin
- Plex
- Kodi
- VLC
- Any player supporting M3U playlists

Features include:

- Relative paths
- Automatic regeneration
- Real-time updates during downloads
- Automatic export after synchronization
- Dedicated `/Playlists` folder

---

## Library Management

- Automatic music organization
- Album and Singles folder structure
- Metadata import
- Duplicate detection
- Automatic database updates
- Safe staging before import
- Library rescan
- Batch deletion

---

## Smart Library Matching

Harmony automatically links songs downloaded before playlist support existed.

If a matching Spotify ID cannot be found, Harmony intelligently searches the library using:

- Track title
- Artist
- Album
- Existing metadata

Successfully matched tracks are permanently linked, allowing historical downloads to appear in playlists without requiring them to be downloaded again.

---

## Modern Web Interface

### Dashboard

- Live download statistics
- Active worker monitoring
- Queue overview
- System activity

### Downloads

- Live download queue
- Worker status
- Real-time progress
- Download history

### Sources

- Spotify playlist sources
- One-click synchronization
- Automatic update detection

### Playlists

New in **v1.2.0**

- Browse synchronized playlists
- Track counts
- Last sync time
- Export status
- Mobile-friendly cards
- Real-time updates

### Library

- Browse downloaded music
- Search library
- Batch deletion
- Metadata overview

### Settings

- Download workers
- Spotify credentials
- Library paths
- Playlist export settings
- Application configuration

---

## Mobile Experience

Harmony is designed mobile-first.

Features include:

- Responsive layouts
- Touch-friendly cards
- Sticky headers
- Floating Quick Add button
- Persistent download status bar
- Skeleton loading animations
- Automatic Light & Dark Mode
- Native-feeling navigation

---

# Download & Sync Pipeline

Harmony uses a safe multi-stage pipeline.

```text
Spotify Playlist
        │
        ▼
Fetch Metadata
        │
        ▼
Update Harmony Playlist Database
        │
        ▼
Generate / Update M3U Playlist
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
Import Engine
        │
        ▼
Music Library
        │
        ▼
Automatic Playlist Rebuild
        │
        ▼
Navidrome / Plex / Jellyfin
```

Downloads are never written directly into the music library. Every file is verified, organized, imported, and immediately reflected in the exported playlist.

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

Create your environment file.

```bash
cp .env.example .env.local
```

Configure Spotify credentials.

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

Build and start Harmony.

```bash
docker compose up -d --build
```

Open Harmony.

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

It continuously synchronizes Spotify playlists, manages your local music library, and automatically exports standard playlists for your media server.

Harmony acts as the **single source of truth** between Spotify and your local music ecosystem.

Spotify → Harmony → Navidrome

No duplicate music.

No manual playlist management.

No broken playlists.

Everything stays synchronized automatically.

---

# Roadmap

## Planned Features

- Scheduled synchronization
- Smart playlists
- Manual playlists
- Advanced library search
- Metadata editor
- Multiple music providers
- Lyrics support
- REST API enhancements
- User authentication
- Multi-user support
- Plugin architecture
- Performance optimizations

---

# Contributing

Contributions are welcome.

If you have ideas, discover a bug, or would like to improve Harmony, feel free to open an issue or submit a pull request.

---

# License

Harmony is licensed under the MIT License.

See the `LICENSE` file for details.

---

<p align="center">
Built for self-hosted music enthusiasts.
</p>
