# Harmony

Harmony is a self-hosted music library manager that downloads music from Spotify URLs, organizes your music collection, and maintains a searchable local library.

Harmony is designed to run on Docker, Synology NAS, Linux servers, or any environment capable of running Python and FFmpeg.

---

## Features

### Download

- Download Spotify tracks
- Download Spotify albums
- Background download queue
- Automatic duplicate detection
- Resume interrupted downloads

### Library Management

- Automatic library organization

```
Artist/
    Album/
        01 - Track.mp3
```

- Automatic metadata extraction
- Library scanner
- Library database
- Duplicate detection

### REST API

- Queue downloads
- View download queue
- Scan library
- Browse library
- Health endpoint

---

## Requirements

- Docker
- FFmpeg
- SpotDL
- Spotify API credentials

---

## Environment Variables

Example:

```env
APP_NAME=Harmony
APP_VERSION=0.6.0

DATABASE_URL=sqlite:////database/harmony.db

MUSIC_PATH=/music

DOWNLOAD_PATH=/downloads
STAGING_PATH=/downloads/staging
FAILED_PATH=/downloads/failed

SPOTIFY_CLIENT_ID=xxxxxxxx
SPOTIFY_CLIENT_SECRET=xxxxxxxx
```

---

## Running

Development

```bash
docker compose \
  --env-file .env.development \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  up --build
```

Production

```bash
docker compose up -d
```

---

## API

### Download Track

```http
POST /api/downloads
```

```json
{
  "url": "https://open.spotify.com/track/..."
}
```

### Download Album

```json
{
  "url": "https://open.spotify.com/album/..."
}
```

### Download Playlist

```json
{
  "url": "https://open.spotify.com/playlist/..."
}
```

> Playlist support is currently experimental due to Spotify Web API authentication limitations.

---

### Library

```
GET /api/library
```

```
POST /api/library/scan
```

---

### Queue

```
GET /api/downloads
```

---

### Health

```
GET /health
```

---

## Current Status

### Implemented

- Track downloads
- Album downloads
- Duplicate detection
- Automatic import
- Library scanner
- SQLite library database
- REST API
- Docker support
- Synology support

### Planned

- Playlist metadata improvements
- Scheduled synchronization
- Automatic artwork management
- Lyrics
- ReplayGain
- Metadata enrichment
- Web interface

---

## License

MIT