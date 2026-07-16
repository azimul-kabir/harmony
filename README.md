# Harmony

Harmony is a lightweight, real-time music manager and downloader designed to sync Spotify playlists, albums, and tracks directly to your local library. Built with a robust Python backend and a lightning-fast, reactive frontend, it is fully optimized for continuous deployment on home servers.

## Features

* **Sleek 5-Section UI:** A polished, media-first interface divided into Dashboard, Downloads, Sources, Library, and Settings to keep management simple and focused.
* **Real-Time UI (No Polling):** Powered by Server-Sent Events (SSE), the dashboard, active tasks, and download queues update instantly with buttery-smooth CSS animations.
* **Smart Queue Management:** Automatically detects duplicate tracks (via database, file system, or active queue) and skips them before wasting bandwidth.
* **Advanced SpotDL Fallback:** Integrates strict metadata matching via Spotify URLs, with an automatic loose-text search fallback (`--dont-filter-results`) to grab hard-to-find regional or extended progressive tracks.
* **Granular Task Control:** Pause, resume, and cancel download tasks dynamically from the UI.
* **Continuous Playlist Sync:** Keep your local library up to date with your Spotify playlists seamlessly in the background.
* **Docker First:** Built explicitly to run in isolated Docker containers with persistent caching and minimal resource footprints.

## Tech Stack

* **Backend:** Python 3.12, FastAPI, SQLAlchemy, SpotDL
* **Database:** SQLite (WAL mode for concurrency)
* **Frontend:** HTML, CSS, Vanilla JavaScript (SSE)
* **Infrastructure:** Docker, Docker Compose

## Deployment

Harmony is designed to be "Docker-First." While it is highly optimized for **Synology NAS**, it will run seamlessly on any system that supports Docker (Windows, macOS, Linux).

### 1. Preparing the Environment

Ensure your host machine has **Docker** and **Docker Compose** installed. Create a directory for your project and define the following local folder structure:
* `database/` (for SQLite storage and SpotDL cache)
* `logs/` (for application logs)
* `music/` (for your library)
* `downloads/` (for staging downloads)

### 2. Configuration

Create a `.env.local` file in your root folder with your environment variables (e.g., Spotify API keys).

*Note for Synology Users:* Use your specific `PUID` and `PGID` in `docker-compose.local.yml` to ensure correct file system permissions for your media shared folders.

### 3. Deploying

Navigate to your project directory and run the following command to spin up the container:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
