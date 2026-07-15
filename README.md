# Harmony 🎵

Harmony is a lightweight, real-time music manager and downloader designed to sync Spotify playlists, albums, and tracks directly to your local library. Built with a robust Python backend and a lightning-fast, reactive frontend, it is fully optimized for continuous deployment on home servers like Synology NAS.

## ✨ Features

* **Real-Time UI (No Polling):** Powered by Server-Sent Events (SSE), the dashboard, active tasks, and download queues update instantly with buttery-smooth CSS animations.
* **Smart Queue Management:** Automatically detects duplicate tracks (via database, file system, or active queue) and skips them before wasting bandwidth.
* **Granular Task Control:** Pause, resume, and cancel download tasks dynamically from the UI.
* **Continuous Playlist Sync:** Keep your local library up to date with your Spotify playlists. The sync engine accurately calculates missing tracks and updates gracefully.
* **Docker First:** Built explicitly to run in isolated Docker containers with minimal resource footprints, perfect for NAS environments.

## 🛠 Tech Stack

* **Backend:** Python, FastAPI, SQLAlchemy, SpotDL
* **Database:** SQLite
* **Frontend:** HTML, CSS, Vanilla JavaScript (SSE)
* **Infrastructure:** Docker, Docker Compose

## 🚀 Deployment (Synology NAS)

Harmony is optimized for deployment on Synology NAS using Docker Compose and standard user permissions to prevent root-owned file locks.

1. **Prepare Directories:**
   Create the necessary volume folders on your NAS:
   * `/volume1/docker/harmony/database`
   * `/volume1/docker/harmony/logs`
   * `/volume1/music/library`
   * `/volume1/music/incoming`

2. **Configure Environment:**
   Create a `.env.local` file with your environment variables (e.g., Spotify API keys, PUID/PGID).

3. **Deploy:**
   Use the local override configuration to spin up the container:
   ```bash
   sudo docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
