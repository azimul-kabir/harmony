# Harmony

![Version](https://img.shields.io/badge/version-0.4.0-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Status](https://img.shields.io/badge/status-active_development-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

*A self-hosted music library manager for collectors who want complete control over their music.*

Harmony is a self-hosted music management platform that combines a local music library with Spotify playlist analysis. It scans your music collection, stores metadata in a local SQLite database, imports Spotify playlists, manages a persistent download queue, and will intelligently determine which songs are already available in your library before downloading anything.

---

## Features

### Library Management

- Scan local music libraries
- Extract metadata using Mutagen
- Store library metadata in SQLite
- Detect new, updated and removed songs
- Library statistics API

### Spotify Integration

- Import Spotify playlists
- SpotDL download integration
- Provider-independent domain models
- REST API for playlist import

### Download Management

- Persistent download queue
- Background download worker
- Automatic job processing
- Job status tracking
- Download history
- Delete completed or failed jobs
- Worker recovery after application restart

### Platform

- FastAPI REST API
- SQLAlchemy ORM
- Docker & Docker Compose
- Automated tests with pytest

---

## Current Status

Version: **0.4.0**

### ✅ Implemented

- Local library scanner
- Metadata extraction
- SQLite database
- Automatic library synchronization
- Library statistics
- Spotify playlist import
- SpotDL integration
- Persistent download queue
- Background download worker
- Download job management
- Download REST API
- Worker recovery on startup
- Docker development environment

### 🚧 In Development

- Retry failed downloads
- Duplicate download prevention
- Automatic library import after download

### 📋 Planned

- Playlist download queue
- Playlist vs library comparison
- Missing song detection
- Duplicate music detection
- Metadata repair
- Album artwork management
- Navidrome integration
- Jellyfin integration
- Scheduled automation
- Web dashboard

---

## API

### Scan Library

```bash
curl -X POST http://localhost:8080/api/library/scan
```

### Library Statistics

```bash
curl http://localhost:8080/api/library/statistics
```

### Import Spotify Playlist

```bash
curl -X POST http://localhost:8080/api/playlists/import \
-H "Content-Type: application/json" \
-d '{
  "url":"https://open.spotify.com/playlist/..."
}'
```

### Queue Download

```bash
curl -X POST http://localhost:8080/api/downloads \
-H "Content-Type: application/json" \
-d '{
  "spotify_url":"https://open.spotify.com/track/...",
  "title":"Attention",
  "artist":"Charlie Puth"
}'
```

### List Download Jobs

```bash
curl http://localhost:8080/api/downloads
```

### Get Download Job

```bash
curl http://localhost:8080/api/downloads/1
```

### Delete Download Job

```bash
curl -X DELETE http://localhost:8080/api/downloads/1
```

---

## Technology Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- SQLite
- Mutagen
- SpotDL
- yt-dlp
- FFmpeg
- Docker
- Pytest

---

## Project Structure

```
app/
├── api/
├── core/
├── database/
├── domain/
├── downloaders/
├── mappers/
├── schemas/
├── services/
├── workers/
├── static/
└── templates/

database/
logs/
music/
tests/
```

---

## Roadmap

### v0.5.0

- Retry failed downloads
- Prevent duplicate download jobs
- Automatic library import after successful downloads

### v0.6.0

- Playlist download queue
- Playlist vs library comparison
- Missing song detection

### v0.7.0

- Duplicate music detection
- Metadata improvements
- Album artwork management

### v1.0.0

- Web dashboard
- Scheduled synchronization
- Multi-provider support
- Navidrome & Jellyfin integration

---

## Vision

Harmony aims to become an intelligent self-hosted music management platform. Rather than simply downloading music, Harmony understands your existing collection, compares it with streaming playlists, downloads only what is missing, and keeps your library organized automatically through a modern REST API and background processing engine.

---

## License

MIT License