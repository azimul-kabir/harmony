# Harmony

Harmony is a self-hosted music downloader and library manager that automatically downloads, organizes, and synchronizes your music library from Spotify.

Built for home servers, Docker, and NAS devices, Harmony combines an automated download pipeline with a modern web interface to create a continuously synchronized local music collection.

**Current Version:** **v1.0.0**

---

## Features

### Downloads

- Download Spotify tracks
- Download Spotify albums
- Download Spotify playlists
- Multi-worker concurrent downloads
- Background download queue
- Automatic retry support
- Download staging pipeline
- SpotDL integration

---

### Playlist Synchronization

- Save Spotify playlists as Sync Sources
- Detect newly added tracks
- Download only missing songs
- Ignore existing library content
- Queue only new downloads
- One-click playlist synchronization

---

### Library Management

- Automatic music organization
- Album and Singles folder structure
- Duplicate detection
- Metadata import
- Automatic library database updates
- Safe staging before import
- Library rescan
- Batch deletion

---

### Web Interface

- Dashboard
- Downloads
- Sources
- Library
- Settings
- Responsive mobile layout
- Desktop layout
- Light Mode
- Dark Mode
- Automatic OS Theme Support

---

### Download Pipeline

Harmony uses a safe multi-stage download pipeline.

```
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

Downloads are never written directly into the music library until they have been successfully imported and verified.

---

## Technology Stack

### Backend

- Python 3.12
- FastAPI
- SQLAlchemy
- SpotDL

### Frontend

- HTML5
- CSS3
- Vanilla JavaScript

### Database

- SQLite

### Deployment

- Docker
- Docker Compose
- Synology NAS
- Linux
- macOS

---

## Installation

Clone the repository.

```bash
git clone https://github.com/azimul-kabir/harmony.git

cd harmony
```

Create an environment file.

```text
.env.local
```

Configure your Spotify API credentials.

```text
SPOTIFY_CLIENT_ID=xxxxxxxxxxxxxxxx
SPOTIFY_CLIENT_SECRET=xxxxxxxxxxxxxxxx
```

Build and start Harmony.

```bash
docker compose up -d --build
```

Open your browser.

```
http://localhost:8080
```

---

## Roadmap

Future releases will continue expanding Harmony with features including:

- Enhanced Library browser
- Advanced metadata editor
- Search and filtering
- Smart collections
- Scheduled synchronization
- Additional music source support
- Improved real-time updates

---

## License

MIT License
