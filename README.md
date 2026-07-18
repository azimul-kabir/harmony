# Harmony

<p align="center">
  <img src="docs/images/logo.png" alt="Harmony Logo" width="160">
</p>

<p align="center">
  <strong>A self-hosted music downloader and library manager for Spotify.</strong><br>
  Automatically download, organize, and synchronize your music library with a modern web interface.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.1.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/docker-supported-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/platform-Synology%20NAS-success" alt="Synology">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

---

Harmony is a self-hosted music downloader and library manager that automatically downloads, organizes, and synchronizes your Spotify music collection. Built for Docker, home servers, and NAS devices, Harmony combines an automated download pipeline with a responsive web interface to maintain a continuously synchronized local music library.

> **Current Version:** **v1.1.0**

---

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Download Pipeline](#download-pipeline)
- [Technology Stack](#technology-stack)
- [Installation](#installation)
- [Configuration](#configuration)
- [Directory Structure](#directory-structure)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

# Features

## Downloads

- Download Spotify tracks
- Download Spotify albums
- Download Spotify playlists
- Background download queue
- Multi-worker concurrent downloads
- Automatic retry support
- Download staging pipeline
- SpotDL integration
- Live download progress
- Queue management

---

## Playlist Synchronization

- Save Spotify playlists as Sync Sources
- One-click synchronization
- Detect newly added tracks
- Download only missing songs
- Skip existing library content
- Automatic duplicate detection
- Task-based synchronization workflow

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

## Modern Web Interface

### Dashboard

- Live download statistics
- Active worker monitoring
- Queue overview
- System activity

### Downloads

- Live download queue
- Worker status
- Real-time progress updates
- Download history

### Sources

- Manage playlist sync sources
- One-click synchronization
- Automatic update detection

### Library

- Browse downloaded music
- Search library
- Batch delete
- Metadata overview

### Settings

- Configure download workers
- Library paths
- Spotify credentials
- Application preferences

---

## Mobile Experience

Harmony is designed with a mobile-first interface.

Features include:

- Responsive layouts
- Touch-friendly cards
- Sticky headers
- Floating Quick Add button
- Persistent download status bar
- Skeleton loading animations
- Light & Dark Mode
- Automatic OS theme detection

---

# Screenshots

> Screenshots coming soon.

```
Dashboard
Downloads
Library
Sources
Settings
```

---

# Download Pipeline

Harmony uses a safe multi-stage processing pipeline to ensure downloaded files are verified before entering your music library.

```text
Spotify
    │
    ▼
Download Queue
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
SQLite Database
```

Downloads are never written directly into your library. Every file is first downloaded into a staging directory, verified, organized, and only then imported into the final music collection.

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

## Clone the repository

```bash
git clone https://github.com/azimul-kabir/harmony.git
cd harmony
```

---

## Create an environment file

```bash
cp .env.example .env.local
```

---

## Configure Spotify credentials

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

---

## Build and start Harmony

```bash
docker compose up -d --build
```

---

## Open Harmony

```
http://localhost:8080
```

---

# Configuration

Example directory structure:

```text
/music
/staging
/database
/config
```

Typical Docker volume mapping:

| Container | Host |
|------------|------|
| /music | Music Library |
| /staging | Temporary Downloads |
| /config | Configuration |
| /database | SQLite Database |

---

# Directory Structure

```text
app/
├── api/
├── core/
├── database/
├── models/
├── services/
├── static/
│   ├── css/
│   └── js/
├── templates/
├── workers/
└── main.py
```

---

# Why Harmony?

Harmony automates the entire process of building and maintaining a local music collection.

Instead of manually downloading songs, organizing folders, checking duplicates, and updating playlists, Harmony continuously handles everything in the background.

Designed for always-on servers, Harmony works especially well on Docker hosts and Synology NAS devices.

---

# Roadmap

## Planned Features

- [ ] Scheduled playlist synchronization
- [ ] Advanced library search
- [ ] Smart collections
- [ ] Metadata editor
- [ ] Playlist management
- [ ] Better album artwork handling
- [ ] Additional music providers
- [ ] REST API improvements
- [ ] User authentication
- [ ] Multi-user support
- [ ] Plugin architecture
- [ ] Performance optimizations

---

# Development

Run Harmony locally:

```bash
python -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload
```

---

# Contributing

Contributions are welcome.

If you have ideas for improvements or discover a bug, feel free to open an issue or submit a pull request.

---

# License

This project is licensed under the MIT License.

See the `LICENSE` file for details.

---

<p align="center">
Made with ❤️ for self-hosted music enthusiasts.
</p>
