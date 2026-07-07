# Harmony

*A self-hosted music library manager for collectors who want complete control over their music.*

Harmony is a self-hosted music library manager designed for music collectors who want complete control over their music collection.

It scans your local music library, extracts metadata, keeps a synchronized database of your collection, and lays the foundation for intelligent Spotify playlist analysis and automated downloads.

---

## Features

### Current

- Music library scanning
- Metadata extraction using Mutagen
- SQLite music library database
- Automatic library synchronization
  - Detect new songs
  - Detect updated songs
  - Remove missing songs
- Library statistics API
- FastAPI REST API
- Docker support
- Automated tests with pytest

---

## In Development

- Spotify Playlist Analyzer
- Playlist vs Library comparison
- Missing song detection
- Download queue integration

---

## Planned Features

- SpotDL integration
- Duplicate song detection
- Metadata repair and normalization
- Album artwork management
- Library organization tools
- Navidrome integration
- Jellyfin integration
- Web dashboard
- Scan history
- Automation and scheduled scans

---

## Technology Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- SQLite
- Mutagen
- Docker
- Pytest

---

## Project Structure

```
app/
├── api/
├── core/
├── database/
├── services/
├── static/
└── templates/

tests/
music/
database/
logs/
```

---

## Current Version

**v0.2.0**

---

## Roadmap

### Completed

- Project foundation
- Docker development environment
- SQLite database
- Music metadata extraction
- Library scanner
- Library synchronizer
- Library statistics
- Basic automated testing

### In Progress

- Spotify Playlist Analyzer

### Planned

- Playlist comparison engine
- Download manager
- Duplicate detection
- Metadata management
- Web dashboard
- Scheduled synchronization

---

## Development

Start the application:

```bash
docker compose up --build
```

Run the test suite:

```bash
docker compose exec harmony pytest
```

Scan the music library:

```bash
curl -X POST http://localhost:8080/api/library/scan
```

View library statistics:

```bash
curl http://localhost:8080/api/library/statistics
```

---

## Vision

Harmony aims to become a complete self-hosted music management platform that combines local music libraries with modern streaming services. Rather than replacing existing tools, Harmony will help users organize, synchronize, analyze, and expand their personal music collections while remaining fully under their control.

---

## License

MIT License