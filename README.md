# Harmony

*A self-hosted music library manager for collectors who want complete control over their music.*

> **Current Version:** v0.4.0  
> 🚧 Active development

Harmony is a self-hosted music management platform that combines a local music library with Spotify playlist analysis. It scans your music collection, stores metadata in a local SQLite database, imports Spotify playlists, manages a persistent download queue, and intelligently determines which songs are already available in your library before downloading anything.

---

# Features

## Library Management

- Scan local music libraries
- Extract metadata using Mutagen
- Store library metadata in SQLite
- Detect new, updated and removed songs
- Incremental library synchronization
- Library statistics API

## Spotify Integration

- Import Spotify playlists
- SpotDL download integration
- Provider-independent architecture
- REST API

## Download Management

- Persistent download queue
- Background download worker
- Automatic job processing
- Job status tracking
- Download history
- Delete completed or failed jobs
- Automatic recovery after application restart

## Platform

- FastAPI REST API
- SQLAlchemy ORM
- SQLite
- Docker & Docker Compose
- Automated tests with pytest

---

# Current Status

**Version:** **0.4.0**

## ✅ Implemented

- Local library scanner
- Metadata extraction
- SQLite persistence
- Automatic library synchronization
- Library statistics
- Spotify playlist import
- Playlist comparison
- SpotDL integration
- Persistent download queue
- Background download worker
- Download job management
- Download REST API
- Worker recovery after restart
- Docker development environment

## 🚧 In Development

- Retry failed downloads
- Duplicate download prevention
- Automatic library import after successful downloads

## 📋 Planned

- Playlist download queue
- Smart playlist vs library comparison
- Missing song detection
- Duplicate music detection
- Metadata repair
- Album artwork management
- Navidrome integration
- Jellyfin integration
- Scheduled automation
- Web dashboard

---

# Quick Start

## Clone the repository

```bash
git clone https://github.com/azimul-kabir/harmony.git
cd harmony
```

## Configure the application

```bash
cp .env.example .env
```

> The default configuration works without modification.  
> Update `.env` only if you want to customize paths or use the official Spotify API credentials.

## Start Harmony

```bash
docker compose up --build
```

## Verify the installation

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{
  "status": "ok",
  "version": "0.4.0"
}
```

---

# API

## Scan Library

```bash
curl -X POST http://localhost:8080/api/library/scan
```

## Library Statistics

```bash
curl http://localhost:8080/api/library/statistics
```

## Import Spotify Playlist

```bash
curl -X POST http://localhost:8080/api/playlists/import \
-H "Content-Type: application/json" \
-d '{
  "url":"https://open.spotify.com/playlist/..."
}'
```

## Queue Download

```bash
curl -X POST http://localhost:8080/api/downloads \
-H "Content-Type: application/json" \
-d '{
  "spotify_url":"https://open.spotify.com/track/...",
  "title":"Attention",
  "artist":"Charlie Puth"
}'
```

## List Download Jobs

```bash
curl http://localhost:8080/api/downloads
```

## Get Download Job

```bash
curl http://localhost:8080/api/downloads/1
```

## Delete Download Job

```bash
curl -X DELETE http://localhost:8080/api/downloads/1
```

---

# Technology Stack

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

# Project Structure

```
app/
├── api/
├── core/
├── database/
├── domain/
├── downloaders/
├── exceptions/
├── mappers/
├── providers/
├── schemas/
├── services/
├── templates/
└── workers/

database/
docs/
downloads/
logs/
test_music/
tests/
```

---

# Roadmap

## v0.5.0

- Retry failed downloads
- Prevent duplicate download jobs
- Automatic library import after successful downloads

## v0.6.0

- Playlist download queue
- Smart playlist vs library comparison
- Missing song detection

## v0.7.0

- Duplicate music detection
- Metadata improvements
- Album artwork management

## v1.0.0

- Web dashboard
- Scheduled synchronization
- Multi-provider support
- Navidrome integration
- Jellyfin integration

---

# Known Limitations

- Downloading from YouTube Music may fail in cloud development environments (such as GitHub Codespaces) because YouTube occasionally requires bot verification.
- The same code works correctly in self-hosted environments such as Synology NAS and other local Docker deployments.

---

# Vision

Harmony aims to become an intelligent, self-hosted music management platform for serious music collectors.

Rather than simply downloading music, Harmony understands your existing collection, compares it with streaming playlists, downloads only what is missing, and keeps your library organized automatically through a modern REST API and background processing engine.

---

# License

MIT License