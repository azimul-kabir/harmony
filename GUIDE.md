## Harmony - A Self-Hosted Spotify Downloader & Library Manager

Hi everyone!

I'd like to share a small project I've been building over the last few months called **Harmony**. 

I'm **not a software developer**. I'm actually a banker. I built Harmony with the help of AI because I couldn't find a music downloader that worked the way I wanted. AI handled most of the heavy coding while I focused on designing the workflow, testing, and improving the user experience. It's been an amazing learning journey.

The biggest frustration that pushed me to build Harmony was duplicate downloads. 

I have hundreds of Spotify playlists, and the same song often appears in many of them. Most downloaders simply download everything again, wasting storage space and making a massive mess of the library. I wanted something smarter that would remember what already existed and only download what was actually missing.

That idea eventually became Harmony.

### What Harmony Does

**Core Features**
*   Download Spotify tracks, albums, and playlists.
*   **Smart Duplicate Detection:** Automatically detects existing songs before downloading to maintain a clean library.
*   **Automated Organization:** Neatly sorts music into Artist → Album folders.
*   **Continuous Sync:** Sync Spotify playlists in the background without freezing the UI.

**UI & Experience**
*   Clean, 5-section web interface (Dashboard, Downloads, Sources, Library, Settings).
*   Zero-latency, real-time download progress using Server-Sent Events (SSE).
*   Built-in library browser with batch deletion and rescan capabilities.
*   Responsive design with Light/Dark mode and mobile-friendly navigation.

**Under the Hood**
*   Multi-threaded background queue for simultaneous downloads.
*   Smart fallback search to grab hard-to-find regional or extended tracks.
*   Runs completely locally on your own computer or NAS via Docker.

### Harmony + Navidrome

Harmony is designed to be the perfect companion to **Navidrome**. Harmony handles the acquisition and organization, and Navidrome handles the streaming.

```text
Spotify
    │
    ▼
 Harmony
 • Download
 • Organize
 • Sync Playlists
 • Detect Duplicates
    │
    ▼
 Music Library
    │
    ▼
 Navidrome
    │
    ▼
 Phone • Tablet • PC • Browser
```

Once Harmony imports new music, Navidrome automatically indexes it, making it immediately available everywhere.

### Recommended Music Apps

Harmony works beautifully with any Subsonic-compatible client through Navidrome:
*   **iPhone / iPad:** Amperfy/Arpeggi
*   **Android:** Symfonium
*   **Windows / macOS / Linux:** Feishin
*   **Web:** Built-in Navidrome Player

### Installation

Harmony runs anywhere Docker is available.

**Windows / macOS / Linux**
1. Install Docker & Docker Compose.
2. Clone the repository.
3. Configure your `.env.local` file.
4. Run: `docker compose up -d`

**Synology NAS**
1. Install Container Manager.
2. Clone the repository onto your NAS.
3. Configure your `.env.local` file.
4. Deploy using Docker Compose.
5. Point Navidrome to Harmony's Music folder.

That's it. Open your browser, add a Spotify playlist, and Harmony takes care of the rest.

### Current Status

Harmony has just reached its **v1.0.0** milestone and is highly stable for everyday use. 

I'm continuing to improve it, and suggestions, feedback, or feature requests are always welcome. If you've also been frustrated by duplicate downloads and messy music folders, I'd love to hear your thoughts!

**GitHub Repository:** [https://github.com/azimul-kabir/harmony](https://github.com/azimul-kabir/harmony)

## Download bulk actions

Downloads can be selected only from the current visible, bounded Downloads feed. The selection toolbar supports retrying failed or cancelled records, cancelling queued or running records, clearing selected terminal history, and clearing all completed or all failed/cancelled history. Eligibility is returned by the server per record and mixed selections safely skip ineligible records.

History clearing removes only terminal download records. It never deletes downloaded music files, Library records, or artwork cache, and it never removes active or queued work. Requests are limited to 100 selected IDs; responses contain only aggregate counts, so repeated terminal-history clearing is safe and reports zero changes when there is nothing left. On mobile the toolbar wraps into full-size touch controls without horizontal scrolling.
