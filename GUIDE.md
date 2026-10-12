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
*   Responsive web interface with Dashboard, Downloads, Sources, Playlists, Library, and Settings.
*   Zero-latency, real-time download progress using Server-Sent Events (SSE).
*   Built-in library browser with batch deletion and rescan capabilities.
*   Responsive design with Light/Dark mode and mobile-friendly navigation.

**Under the Hood**
*   Multi-threaded background queue for simultaneous downloads.
*   Spotify downloads use a bounded yt-dlp candidate search, then a bounded
    SpotDL rescue when needed. Every downloaded candidate must pass the same
    strict identity checks before import.
*   Artist, title, recording-version markers, and reliable duration are checked
    before import. If the Spotify-linked recording is unavailable, the item
    remains unavailable rather than making the playlist appear complete with a
    remix, instrumental, karaoke, live, cover, or unrelated recording.
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
3. Copy `.env.example` to `.env`, set a strong `WEB_AUTH_PASSWORD`, and configure `MUSIC_HOST_PATH` and `DOWNLOAD_HOST_PATH`.
4. Run: `docker compose up -d`

**Synology NAS**
1. Install Container Manager.
2. Clone the repository onto your NAS.
3. Copy `.env.example` to `.env`, set a strong `WEB_AUTH_PASSWORD`, and configure `MUSIC_HOST_PATH` and `DOWNLOAD_HOST_PATH`.
4. Deploy using Docker Compose.
5. Point Navidrome to Harmony's Music folder.

That's it. Open your browser, add a Spotify playlist, and Harmony takes care of the rest.

### Correcting Library Metadata and Artwork

1. Open **Library → Songs** and select **Edit** beside an available song.
2. Correct the saved title, artist, album, album artist, genre, year, track, or
   disc fields directly when you already know the right values.
3. For provider assistance, edit the separate **Find metadata** title, artist,
   and album inputs. These begin with the current tags but can be completely
   replaced—for example, shorten a video-style title and replace an uploader
   name with the actual recording artist.
4. Choose **Search MusicBrainz**, select a likely match, and review every copied
   value. A search result is never applied automatically.
5. Optionally select a JPEG, PNG, or WebP artwork file (maximum 15 MB), or keep
   the selected result's Cover Art Archive preview for import.
6. Choose **Save changes**. Harmony updates the audio tags, refreshes the
   Library index, and then applies the chosen artwork. A failed artwork import
   is reported separately so the metadata save is not hidden.

The editor is unavailable for missing files. Manual and imported artwork update
Harmony's canonical artwork cache and do not replace artwork embedded inside
the audio file.

### Backing Up Harmony

Open **Settings → Operations** and choose **Download backup** to save a ZIP of
Harmony's database (Library index, Sources, playlists, history, and settings)
and its artwork cache. To move to a new machine or recover, choose **Restore
backup** on the new install, then restart Harmony. Your music files are not in
the backup, so keep a copy of the music folder as well.

### Current Status

Harmony is at **v3.1.0**, with review-first local uploads, a per-song Library
metadata editor, backup and restore, Navidrome 0.64 ID reconciliation, a
redesigned interface, five mobile tabs, and a manual YouTube-link option for
every failed download. See the [v3.1.0 release notes](docs/releases/v3.1.0.md)
before upgrading, and the [changelog](CHANGELOG.md) for the complete history.
Harmony v1.6.0 was never published.

I'm continuing to improve it, and suggestions, feedback, or feature requests are always welcome. If you've also been frustrated by duplicate downloads and messy music folders, I'd love to hear your thoughts!

**GitHub Repository:** [https://github.com/azimul-kabir/harmony](https://github.com/azimul-kabir/harmony)

## Download bulk actions

Downloads can be selected only from the current visible, bounded Downloads feed. The selection toolbar supports retrying eligible failed records, cancelling queued or running records, clearing selected terminal history, and clearing all completed or all failed/cancelled history. The completed-history action also clears skipped records. Eligibility is returned by the server per record and mixed selections safely skip ineligible records.

History clearing removes only terminal download records. It never deletes downloaded music files, Library records, or artwork cache, and it never removes active or queued work. Requests are limited to 100 selected IDs; responses contain only aggregate counts, so repeated terminal-history clearing is safe and reports zero changes when there is nothing left. On mobile the toolbar wraps into full-size touch controls without horizontal scrolling.
