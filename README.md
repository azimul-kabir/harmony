# Harmony

*A self-hosted music library manager for collectors who want complete control over their music.*

Harmony is a self-hosted music management platform that combines a local music library with Spotify playlist analysis. It scans your music collection, stores metadata in a local database, imports Spotify playlists through SpotDL, and will intelligently determine which songs are already available in your library before downloading anything.

---

## Features

### Library Management

- Scan local music libraries
- Extract metadata using Mutagen
- Store library metadata in SQLite
- Detect new, updated and removed songs
- Library statistics API

### Spotify Integration

- Import Spotify playlists using SpotDL
- Provider-independent domain models
- REST API for playlist import

### Platform

- FastAPI REST API
- Docker & Docker Compose
- Automated tests with pytest

---

## Current Status

### ✅ Implemented

- Local library scanner
- Metadata extraction
- SQLite database
- Automatic library synchronization
- Library statistics
- Spotify playlist import
- SpotDL integration
- Docker development environment
- REST API

### 🚧 In Development

- Playlist vs library comparison
- Missing song detection
- Download queue
- Download engine

### 📋 Planned

- Duplicate detection
- Metadata repair
- Album artwork management
- Playlist synchronization
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

Example response:

```json
{
  "name": "Test",
  "track_count": 3,
  "tracks": [
    {
      "title": "Attention",
      "artist": "Charlie Puth",
      "album": "Voicenotes"
    }
  ]
}
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
├── static/
└── templates/

database/
logs/
music/
tests/
```

---

## Roadmap

### v0.3.x

- Playlist comparison
- Missing song detection

### v0.4.x

- Download queue
- Smart downloading

### v0.5.x

- Duplicate detection
- Metadata improvements

### v0.6+

- Web dashboard
- Scheduled synchronization
- Multi-provider support

---

## Vision

Harmony aims to become an intelligent self-hosted music management platform. Rather than simply downloading music, Harmony understands your existing collection, compares it with streaming playlists, downloads only what is missing, and keeps your library organized automatically.

---

## License

MIT License