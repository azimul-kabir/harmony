const LIBRARY_PREFERENCES_KEY = "harmony.library.preferences.v1";
const LIBRARY_UPLOAD_RECOVERY_KEY = "harmony.library.upload.recovery.v1";
const DEFAULT_BITRATE_RANGES = {
    lossless: { min: 900000, max: null },
    high: { min: 320000, max: null },
    standard: { min: 192000, max: 319999 },
    compact: { min: null, max: 191999 },
};
const savedPreferences = readLibraryPreferences();

const libraryState = {
    songs: [],
    albums: [],
    artists: [],
    filterOptions: null,
    filteredSongs: [],
    filteredAlbums: [],
    filteredArtists: [],
    view: "songs",
    sort: savedPreferences.sort || "artist",
    filters: {
        artist: savedPreferences.filters?.artist || "",
        album: savedPreferences.filters?.album || "",
        genre: savedPreferences.filters?.genre || "",
        codec: savedPreferences.filters?.codec || "",
        bitrate: savedPreferences.filters?.bitrate || "",
        downloaded_today: Boolean(savedPreferences.filters?.downloaded_today),
        recently_added: Boolean(savedPreferences.filters?.recently_added),
        missing_artwork: Boolean(savedPreferences.filters?.missing_artwork),
        missing_metadata: Boolean(savedPreferences.filters?.missing_metadata),
    },
    filterPanelOpen: Boolean(savedPreferences.filterPanelOpen),
    query: "",
    requestedAlbumKey: null,
    requestedSongId: null,
    requestedAvailability: null,
    searchTotal: 0,
    searchRequest: 0,
    pages: { songs: 1, albums: 1, artists: 1 },
    pageSize: 24,
    selectedSongs: new Set(),
    bulkTaskId: null,
    bulkPollTimer: null,
};

let searchTimer = null;
let refreshTimer = null;
const libraryUploadState = { batchId: null, items: [], summary: null, duplicates: null, taskId: null };

const icons = {
    music: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>`,
    artist: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`,
    recent: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>`,
    quality: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 18V9"></path><path d="M10 18V5"></path><path d="M16 18v-7"></path><path d="M22 18V3"></path></svg>`,
    artwork: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-5-5L5 21"></path></svg>`,
    metadata: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 6h16"></path><path d="M4 12h10"></path><path d="M4 18h7"></path><circle cx="18" cy="16" r="3"></circle><path d="m20.2 18.2 1.8 1.8"></path></svg>`,
    download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>`,
    modified: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 8v5l3 2"></path><path d="M3.05 11a9 9 0 1 1 .5 4"></path><path d="M3 16v-5h5"></path></svg>`,
    album: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="2"></circle></svg>`,
    favorite: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"></path></svg>`,
};

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        let message = `Request failed: ${response.status}`;
        try {
            const payload = await response.json();
            message = payload.detail || payload.error?.message || message;
        } catch (_) { /* Keep the bounded HTTP fallback. */ }
        throw new Error(message);
    }
    return response.json();
}

async function loadDuplicateCandidates() {
    const status = document.getElementById("duplicate-review-status");
    const target = document.getElementById("duplicate-review-groups");
    const tier = document.getElementById("duplicate-tier").value;
    status.textContent = "Analyzing indexed identity signals…";
    target.innerHTML = "";
    try {
        const result = await fetchJson(`/api/library/duplicates?limit=200${tier ? `&tier=${encodeURIComponent(tier)}` : ""}`);
        status.textContent = `${result.total} candidate ${result.total === 1 ? "group" : "groups"} · ${result.duplicate_songs} indexed songs`;
        target.innerHTML = result.items.map((group) => `
            <article class="duplicate-group-card">
                <header><div><h3>${escapeHtml(group.songs[0]?.title || "Untitled candidates")}</h3><small>${escapeHtml(group.songs[0]?.artist || "Unknown artist")} · ${group.song_count} candidates</small></div><span class="duplicate-tier-badge">${escapeHtml(group.tier)} · ${Math.round(group.confidence * 100)}%</span></header>
                <p class="duplicate-evidence">${escapeHtml([...new Set(group.evidence.map((item) => item.message))].join(" · "))}</p>
                <div class="duplicate-song-list">${group.songs.map((song) => `
                    <div class="duplicate-song-row">
                        ${song.cover_url
                            ? `<img class="duplicate-song-artwork" src="${escapeHtml(song.cover_url)}" alt="" loading="lazy" data-duplicate-artwork>`
                            : '<span class="duplicate-song-artwork duplicate-song-artwork-placeholder" aria-hidden="true">♪</span>'}
                        <div class="duplicate-song-copy"><strong>${escapeHtml(song.filename)}</strong><small>${escapeHtml(song.album || "Album unknown")} · ${escapeHtml(song.codec || "codec unknown")}</small>${song.id === group.recommended_keep_id ? '<span class="duplicate-keeper">Suggested keeper — review before resolving</span>' : ""}</div>
                        <span class="duplicate-song-stat duplicate-song-duration"><small>Duration</small>${escapeHtml(formatDuration(song.duration))}</span>
                        <span class="duplicate-song-stat duplicate-song-bitrate"><small>Bitrate</small>${escapeHtml(formatBitrate(song.bitrate))}</span>
                        <span class="duplicate-song-stat duplicate-song-size"><small>File size</small>${escapeHtml(formatBytes(song.file_size))}</span>
                        <label class="duplicate-keeper-control"><input type="radio" name="duplicate-keeper-${group.id}" value="${song.id}" ${song.id === group.recommended_keep_id ? "checked" : ""}> Keep this file</label>
                    </div>`).join("")}</div>
                <div class="library-actions"><button class="btn-secondary" type="button" data-preview-duplicate-resolution="${group.id}">Preview resolution</button></div>
                <div data-duplicate-resolution="${group.id}"></div>
            </article>`).join("") || '<p class="library-search-status">No duplicate candidates match this tier.</p>';
        target.querySelectorAll("[data-preview-duplicate-resolution]").forEach((button) => {
            button.addEventListener("click", () => previewDuplicateResolution(button.dataset.previewDuplicateResolution));
        });
        target.querySelectorAll("[data-duplicate-artwork]").forEach((image) => {
            image.addEventListener("error", () => {
                const placeholder = document.createElement("span");
                placeholder.className = "duplicate-song-artwork duplicate-song-artwork-placeholder";
                placeholder.setAttribute("aria-hidden", "true");
                placeholder.textContent = "♪";
                image.replaceWith(placeholder);
            }, {once: true});
        });
    } catch (_) {
        status.textContent = "Duplicate analysis is unavailable.";
    }
}

async function previewDuplicateResolution(groupId) {
    const target = document.querySelector(`[data-duplicate-resolution="${groupId}"]`);
    const keeper = document.querySelector(`input[name="duplicate-keeper-${groupId}"]:checked`);
    if (!keeper) { target.textContent = "Choose exactly one file to keep."; return; }
    target.innerHTML = '<p class="library-search-status">Revalidating this duplicate group…</p>';
    try {
        const preview = await fetchJson(`/api/library/duplicates/${groupId}/resolution-preview?keep_song_id=${keeper.value}`);
        const playlistCount = preview.playlist_impacts.reduce((total, item) => total + item.playlists.length, 0);
        target.innerHTML = `<article class="metadata-suggestion-card duplicate-resolution-preview">
            <strong>Resolution preview</strong>
            <p>Keep Song ${preview.keep_song_id}; remove ${preview.remove_song_ids.length} ${preview.remove_song_ids.length === 1 ? "file" : "files"} and reclaim up to ${escapeHtml(formatBytes(preview.reclaimable_bytes))}.</p>
            ${playlistCount ? `<p><strong>Playlist impact:</strong> ${playlistCount} saved playlist ${playlistCount === 1 ? "reference" : "references"} may become unavailable.</p>` : ""}
            ${preview.warnings.map((warning) => `<small>${escapeHtml(warning)}</small>`).join("")}
            <button class="library-bulk-delete" type="button" data-confirm-duplicate-resolution>Delete non-keepers</button>
        </article>`;
        target.querySelector("[data-confirm-duplicate-resolution]").onclick = () => submitDuplicateResolution(preview, target);
    } catch (error) {
        target.textContent = error.message;
    }
}

async function submitDuplicateResolution(preview, target) {
    if (!window.confirm(`Permanently delete ${preview.remove_song_ids.length} non-keeper audio ${preview.remove_song_ids.length === 1 ? "file" : "files"}? Library records will remain marked missing.`)) return;
    const button = target.querySelector("[data-confirm-duplicate-resolution]");
    button.disabled = true;
    const response = await fetch(`/api/library/duplicates/${preview.group_id}/resolve`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...preview, confirm_delete: true, initiated_by: "duplicate-ui"}),
    });
    const result = await response.json();
    if (!response.ok) {
        target.textContent = result.detail || "Duplicate resolution could not be queued.";
        return;
    }
    let task = await fetchJson(`/api/library/bulk/${result.job_id}`);
    while (["queued", "running", "cancelling"].includes(task.status)) {
        target.textContent = `${task.status.replaceAll("_", " ")} · ${task.processed_items}/${task.total_items}`;
        await new Promise((resolve) => setTimeout(resolve, 750));
        task = await fetchJson(`/api/library/bulk/${result.job_id}`);
    }
    target.textContent = task.status === "completed"
        ? "Duplicate resolution completed. Removed files remain as missing Library records."
        : `Duplicate resolution ${task.status.replaceAll("_", " ")}. Review the Library task for details.`;
    await Promise.all([loadDuplicateCandidates(), loadLibraryData({preserveState: true})]);
}

function openDuplicateReview() {
    document.getElementById("duplicate-review-dialog").showModal();
    loadDuplicateCandidates();
}

function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const scaled = value / (1024 ** unit);
    return `${scaled >= 100 || unit === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[unit]}`;
}

function readLibraryPreferences() {
    try {
        return JSON.parse(localStorage.getItem(LIBRARY_PREFERENCES_KEY) || "{}") || {};
    } catch (error) {
        return {};
    }
}

function saveLibraryPreferences() {
    try {
        localStorage.setItem(LIBRARY_PREFERENCES_KEY, JSON.stringify({
            sort: libraryState.sort,
            filters: libraryState.filters,
            filterPanelOpen: libraryState.filterPanelOpen,
        }));
    } catch (error) {
        console.warn("Library preferences could not be saved.", error);
    }
}

function libraryRequestParams({ query = null, limit = null } = {}) {
    const params = new URLSearchParams({ sort_by: libraryState.sort });
    if (query) params.set("q", query);
    if (limit) params.set("limit", String(limit));
    ["artist", "album", "genre", "codec"].forEach((field) => {
        if (libraryState.filters[field]) params.set(field, libraryState.filters[field]);
    });
    const bitrate = libraryState.filterOptions?.bitrate_ranges?.find(
        (range) => range.id === libraryState.filters.bitrate) ||
        DEFAULT_BITRATE_RANGES[libraryState.filters.bitrate];
    if (bitrate?.min != null) params.set("min_bitrate", String(bitrate.min));
    if (bitrate?.max != null) params.set("max_bitrate", String(bitrate.max));
    ["downloaded_today", "recently_added", "missing_artwork", "missing_metadata"].forEach((field) => {
        if (libraryState.filters[field]) params.set(field, "true");
    });
    if (libraryState.requestedAvailability === "missing") params.set("include_missing", "true");
    return params.toString();
}

function projectSongs(songs) {
    const albumMap = new Map();
    const artistMap = new Map();
    songs.forEach((song) => {
        const album = song.album || "Unknown Album";
        const artist = song.album_artist || song.artist || "Unknown Artist";
        const albumKey = `${artist}\u0000${album}`;
        const metadataAlbumKey = libraryAlbumKey(artist, album);
        const albumItem = albumMap.get(albumKey) || {
            album,
            artist,
            metadata_key: metadataAlbumKey,
            cover_url: song.cover_url,
            track_count: 0,
            total_duration: 0,
            sort_added: "",
            sort_modified: "",
            sort_bitrate: 0,
            sort_year: 0,
        };
        albumItem.track_count += 1;
        albumItem.total_duration += Number(song.duration || 0) / 60;
        if (!albumItem.cover_url && song.cover_url) albumItem.cover_url = song.cover_url;
        albumItem.sort_added = maxText(albumItem.sort_added, song.date_added);
        albumItem.sort_modified = maxText(albumItem.sort_modified, song.last_modified);
        albumItem.sort_bitrate = Math.max(albumItem.sort_bitrate, Number(song.bitrate || 0));
        albumItem.sort_year = Math.max(albumItem.sort_year, Number(song.year || 0));
        albumMap.set(albumKey, albumItem);

        const songArtist = song.artist || "Unknown Artist";
        const artistItem = artistMap.get(songArtist) || {
            artist: songArtist,
            song_count: 0,
            albums: new Set(),
            sort_added: "",
            sort_modified: "",
            sort_bitrate: 0,
            sort_duration: 0,
            sort_year: 0,
        };
        artistItem.song_count += 1;
        artistItem.albums.add(album);
        artistItem.sort_added = maxText(artistItem.sort_added, song.date_added);
        artistItem.sort_modified = maxText(artistItem.sort_modified, song.last_modified);
        artistItem.sort_bitrate = Math.max(artistItem.sort_bitrate, Number(song.bitrate || 0));
        artistItem.sort_duration = Math.max(artistItem.sort_duration, Number(song.duration || 0));
        artistItem.sort_year = Math.max(artistItem.sort_year, Number(song.year || 0));
        artistMap.set(songArtist, artistItem);
    });
    return {
        albums: sortProjection(
            [...albumMap.values()].map((album) => ({
                ...album,
                sort_duration: album.total_duration,
                total_duration: Math.round(album.total_duration * 10) / 10,
            })),
            "album",
        ),
        artists: sortProjection(
            [...artistMap.values()].map((artist) => ({
                ...artist,
                album_count: artist.albums.size,
                albums: undefined,
            })),
            "artist",
        ),
    };
}

function maxText(current, value) {
    const next = String(value || "");
    return next > current ? next : current;
}

function libraryNormalize(value, { artist = false } = {}) {
    let result = String(value || "").normalize("NFKC").trim();
    result = result.replace(/\s+/g, " ").replace(/[’‘]/g, "'").replace(/[‐‑‒–—―]/g, "-");
    result = result.replace(/\s*([&/+])\s*/g, " $1 ").replace(/\s+/g, " ").toLocaleLowerCase();
    return artist && result.startsWith("the ") ? result.slice(4) : result;
}

function libraryAlbumKey(artist, album) {
    return `${libraryNormalize(artist, { artist: true })}::${libraryNormalize(album)}`;
}

function sortProjection(items, type) {
    const textField = type === "album" ? "album" : "artist";
    if (libraryState.sort === "artist") {
        return items.sort((a, b) => String(a.artist).localeCompare(String(b.artist)) ||
            String(a[textField]).localeCompare(String(b[textField])));
    }
    if (["album", "title", "alphabetical"].includes(libraryState.sort)) {
        return items.sort((a, b) => String(a[textField]).localeCompare(String(b[textField])));
    }
    const metric = {
        recently_added: "sort_added",
        recently_modified: "sort_modified",
        bitrate: "sort_bitrate",
        duration: "sort_duration",
        year: "sort_year",
    }[libraryState.sort];
    return items.sort((a, b) => (b[metric] || 0) > (a[metric] || 0) ? 1 :
        (b[metric] || 0) < (a[metric] || 0) ? -1 :
            String(a[textField]).localeCompare(String(b[textField])));
}

function populateFilterOptions() {
    const options = libraryState.filterOptions;
    if (!options) return;
    const fields = {
        artist: [options.artists, "All artists"],
        album: [options.albums, "All albums"],
        genre: [options.genres, "All genres"],
        codec: [options.codecs, "All codecs"],
    };
    Object.entries(fields).forEach(([field, [values, emptyLabel]]) => {
        const select = document.getElementById(`filter-${field}`);
        select.innerHTML = `<option value="">${emptyLabel}</option>` + values.map((value) =>
            `<option value="${escapeAttribute(value)}">${escapeHtml(value)}</option>`).join("");
    });
    document.getElementById("filter-bitrate").innerHTML = '<option value="">Any bitrate</option>' +
        options.bitrate_ranges.map((range) =>
            `<option value="${escapeAttribute(range.id)}">${escapeHtml(range.label)}</option>`).join("");
}

function activeFilterCount() {
    return Object.values(libraryState.filters).filter(Boolean).length;
}

function updateFilterControls() {
    ["artist", "album", "genre", "codec", "bitrate"].forEach((field) => {
        document.getElementById(`filter-${field}`).value = libraryState.filters[field];
    });
    ["downloaded_today", "recently_added", "missing_artwork", "missing_metadata"].forEach((field) => {
        document.getElementById(`filter-${field.replaceAll("_", "-")}`).checked = libraryState.filters[field];
    });
    const count = activeFilterCount();
    const badge = document.getElementById("library-filter-count");
    badge.textContent = String(count);
    badge.hidden = count === 0;
    const panel = document.getElementById("library-filter-panel");
    panel.hidden = !libraryState.filterPanelOpen;
    document.getElementById("library-filter-toggle").setAttribute("aria-expanded", String(libraryState.filterPanelOpen));
}

async function loadLibraryData({ preserveState = false } = {}) {
    const loading = document.getElementById("library-loading");
    const errorBox = document.getElementById("library-error");
    if (!preserveState) loading.hidden = false;
    errorBox.hidden = true;

    try {
        const songEndpoint = "/api/library/songs";
        // Songs are the source for the Songs, Albums, and Artists views. Do
        // not let the optional filter-options request hide all three views.
        const songResult = await fetchJson(`${songEndpoint}?${libraryRequestParams()}`);
        const filterOptionsResult = await Promise.allSettled([
            libraryState.filterOptions
                ? Promise.resolve(libraryState.filterOptions)
                : fetchJson("/api/library/filter-options"),
        ]);

        const songs = Array.isArray(songResult) ? songResult : songResult.items;
        const { albums, artists } = projectSongs(songs);
        const filterOptions = filterOptionsResult[0].status === "fulfilled"
            ? filterOptionsResult[0].value
            : libraryState.filterOptions;
        Object.assign(libraryState, { songs, albums, artists, filterOptions });
        if (filterOptionsResult[0].status === "rejected") {
            console.error("Library filter options error:", filterOptionsResult[0].reason);
        }
        populateFilterOptions();
        updateFilterControls();
        updateCounts();
        if (libraryState.query.trim()) {
            await performSearch();
        } else {
            applyFilters();
            renderActiveView();
        }
    } catch (error) {
        console.error("Library load error:", error);
        errorBox.textContent = "Harmony could not load the Library Index. Try again in a moment.";
        errorBox.hidden = false;
    } finally {
        loading.hidden = true;
    }
}

function applyFilters() {
    const query = libraryState.query.toLocaleLowerCase().trim();
    let songs = libraryState.songs;

    if (query) {
        songs = songs.filter((song) => [song.title, song.artist, song.album, song.filename]
            .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
    }

    libraryState.filteredSongs = songs.filter((song) =>
        (!libraryState.requestedSongId || song.id === libraryState.requestedSongId) &&
        (!libraryState.requestedAvailability || song.availability_status === libraryState.requestedAvailability));
    libraryState.filteredAlbums = libraryState.albums.filter((album) =>
        (!query || [album.album, album.artist].some((value) => String(value || "").toLocaleLowerCase().includes(query))) &&
        (!libraryState.requestedAlbumKey || album.metadata_key === libraryState.requestedAlbumKey));
    libraryState.filteredArtists = libraryState.artists.filter((artist) => !query ||
        String(artist.artist || "").toLocaleLowerCase().includes(query));
}

async function performSearch() {
    const query = libraryState.query.trim();
    const status = document.getElementById("library-search-status");
    const request = ++libraryState.searchRequest;
    if (!query) {
        libraryState.searchTotal = 0;
        status.textContent = "";
        applyFilters();
        renderActiveView();
        return;
    }

    status.textContent = "Searching the Library Index…";
    try {
        const result = await fetchJson(`/api/library/search?${libraryRequestParams({ query, limit: 500 })}`);
        if (request !== libraryState.searchRequest) return;

        libraryState.searchTotal = result.total;
        libraryState.filteredSongs = result.items;
        const projections = projectSongs(result.items);
        libraryState.filteredAlbums = projections.albums;
        libraryState.filteredArtists = projections.artists;

        const shown = result.items.length;
        status.textContent = result.total > shown
            ? `${result.total.toLocaleString()} matches · showing first ${shown.toLocaleString()}`
            : `${result.total.toLocaleString()} ${result.total === 1 ? "match" : "matches"}`;
        renderActiveView();
    } catch (error) {
        if (request !== libraryState.searchRequest) return;
        console.error("Library search error:", error);
        status.textContent = error.message || "Search unavailable";
        const errorBox = document.getElementById("library-error");
        errorBox.textContent = error.message || "Harmony could not search the Library Index. Try again in a moment.";
        errorBox.hidden = false;
    }
}

function updateCounts() {
    document.getElementById("songs-count").textContent = libraryState.songs.length.toLocaleString();
    document.getElementById("albums-count").textContent = libraryState.albums.length.toLocaleString();
    document.getElementById("artists-count").textContent = libraryState.artists.length.toLocaleString();
}

function renderActiveView() {
    document.querySelectorAll(".library-view").forEach((view) => {
        view.hidden = view.id !== `view-${libraryState.view}`;
    });

    updateMobileSelectAll();
    if (libraryState.view === "songs") renderSongs();
    if (libraryState.view === "albums") renderAlbums();
    if (libraryState.view === "artists") renderArtists();
}

function renderSongs() {
    const page = pageItems(libraryState.filteredSongs, "songs");
    const body = document.getElementById("library-body");

    if (!page.items.length) {
        body.innerHTML = emptyTable("No songs match this view.");
    } else {
        body.innerHTML = page.items.map((song) => `
            <tr class="${libraryState.selectedSongs.has(song.id) ? "is-selected" : ""}">
                <td class="library-select-cell" data-label="Select"><input type="checkbox" data-select-song="${song.id}" aria-label="Select ${escapeAttribute(song.title || song.filename)}" ${libraryState.selectedSongs.has(song.id) ? "checked" : ""}></td>
                <td data-label="Title">
                    <div class="library-song-title">
                        ${artwork(song.cover_url, "library-song-artwork")}
                        <div class="library-song-copy">
                            <strong>${escapeHtml(song.title || "Unknown title")}</strong>
                            ${song.recently_added ? `<span class="library-recent-badge">Recently Added</span>` : ""}
                        </div>
                    </div>
                </td>
                <td data-label="Artist">${escapeHtml(song.artist || "Unknown artist")}</td>
                <td data-label="Album">${escapeHtml(song.album || "Unknown album")}</td>
                <td data-label="Duration" class="library-mono">${formatDuration(song.duration)}</td>
                <td data-label="Bitrate"><span class="library-bitrate">${formatBitrate(song.bitrate)}</span></td>
                <td data-label="Actions"><div class="library-row-actions">
                    <button class="btn-secondary library-edit-metadata" type="button" data-edit-metadata="${song.id}">Edit</button>
                </div></td>
            </tr>
        `).join("");
    }

    body.querySelectorAll("[data-select-song]").forEach((checkbox) => {
        checkbox.addEventListener("change", () => {
            const songId = Number(checkbox.dataset.selectSong);
            checkbox.checked ? libraryState.selectedSongs.add(songId) : libraryState.selectedSongs.delete(songId);
            checkbox.closest("tr").classList.toggle("is-selected", checkbox.checked);
            updateBulkSelection(page.items);
        });
    });
    body.querySelectorAll("[data-edit-metadata]").forEach((button) => {
        button.addEventListener("click", () => openMetadataEditor(Number(button.dataset.editMetadata)));
    });
    updateBulkSelection(page.items);

    renderPagination("pagination-songs", page, "songs", renderSongs);
}

let metadataEditorSong = null;
let metadataEditorArtworkRelease = null;

function setMetadataForm(song) {
    const form = document.getElementById("metadata-editor-form");
    ["title", "artist", "album", "album_artist", "genre", "year", "track", "disc"].forEach((field) => {
        form.elements[field].value = song[field] ?? song[`${field}_number`] ?? "";
    });
    form.elements.musicbrainz_recording_id.value = song.musicbrainz_recording_id || "";
    form.elements.musicbrainz_release_id.value = "";
}

function openMetadataEditor(songId) {
    metadataEditorSong = libraryState.songs.find((song) => song.id === songId);
    if (!metadataEditorSong) return;
    metadataEditorArtworkRelease = null;
    setMetadataForm(metadataEditorSong);
    document.getElementById("metadata-search-title-input").value = metadataEditorSong.title || "";
    document.getElementById("metadata-search-artist").value = metadataEditorSong.artist || "";
    document.getElementById("metadata-search-album").value = metadataEditorSong.album || "";
    document.getElementById("metadata-artwork-preview").src = metadataEditorSong.cover_url || "";
    document.getElementById("metadata-artwork-file").value = "";
    document.getElementById("metadata-search-results").innerHTML = "";
    document.getElementById("metadata-search-status").textContent = "";
    document.getElementById("metadata-editor-status").textContent = "";
    document.getElementById("metadata-editor-dialog").showModal();
}

async function searchMetadata() {
    const params = new URLSearchParams();
    [["title", "metadata-search-title-input"], ["artist", "metadata-search-artist"], ["album", "metadata-search-album"]].forEach(([field, id]) => {
        const value = document.getElementById(id).value.trim(); if (value) params.set(field, value);
    });
    const status = document.getElementById("metadata-search-status");
    const results = document.getElementById("metadata-search-results");
    status.textContent = "Searching…"; results.innerHTML = "";
    try {
        const payload = await fetchJson(`/api/library/metadata/search?${params}`);
        status.textContent = `${payload.items.length} possible ${payload.items.length === 1 ? "match" : "matches"}`;
        results.innerHTML = payload.items.map((item, index) => `<button type="button" data-metadata-result="${index}" class="metadata-search-result">
            ${item.artwork_url ? `<img src="${escapeAttribute(item.artwork_url)}" alt="" loading="lazy">` : `<span class="library-artwork-placeholder">${icons.music}</span>`}
            <span><strong>${escapeHtml(item.title || "Untitled")}</strong><small>${escapeHtml(item.artist || "Unknown artist")} · ${escapeHtml(item.album || "Unknown album")}${item.year ? ` · ${item.year}` : ""}</small></span>
        </button>`).join("") || "<p>No matches found. Try shorter or corrected search terms.</p>";
        results.querySelectorAll("[data-metadata-result]").forEach((button) => button.onclick = () => {
            const item = payload.items[Number(button.dataset.metadataResult)];
            setMetadataForm(item);
            metadataEditorArtworkRelease = item.release_id || null;
            if (item.artwork_url) document.getElementById("metadata-artwork-preview").src = item.artwork_url;
            results.querySelectorAll("button").forEach((entry) => entry.classList.toggle("is-selected", entry === button));
            status.textContent = "Match copied below. Review every field before saving.";
        });
    } catch (error) { status.textContent = error.message; }
}

async function saveMetadata(event) {
    event.preventDefault();
    if (!metadataEditorSong) return;
    const form = event.currentTarget;
    const status = document.getElementById("metadata-editor-status");
    const payload = {};
    ["title", "artist", "album", "album_artist", "genre", "musicbrainz_recording_id", "musicbrainz_release_id"].forEach((field) => { payload[field] = form.elements[field].value.trim() || null; });
    ["year", "track", "disc"].forEach((field) => { payload[field] = form.elements[field].value === "" ? null : Number(form.elements[field].value); });
    status.textContent = "Saving metadata…";
    try {
        const response = await fetch(`/api/library/songs/${metadataEditorSong.id}/metadata`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || "Metadata could not be saved.");
        const file = document.getElementById("metadata-artwork-file").files[0];
        if (file) {
            const data = new FormData(); data.append("file", file);
            const artworkResponse = await fetch(`/api/artwork/songs/${metadataEditorSong.id}`, {method: "POST", body: data});
            if (!artworkResponse.ok) { const error = await artworkResponse.json(); throw new Error(error.detail || "Artwork could not be saved."); }
        } else if (metadataEditorArtworkRelease) {
            const artworkResponse = await fetch(`/api/library/songs/${metadataEditorSong.id}/metadata/artwork`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({release_id: metadataEditorArtworkRelease})});
            if (!artworkResponse.ok) { const error = await artworkResponse.json(); throw new Error(error.detail || "Artwork could not be imported."); }
        }
        // Navidrome reads tags and embedded covers from the shared audio file.
        // Start an incremental scan after either metadata or artwork changes.
        fetch("/api/navidrome/rescan?full_scan=false", {method: "POST"}).catch(() => {});
        status.textContent = "Saved."; await loadLibraryData({preserveState: true}); setTimeout(() => document.getElementById("metadata-editor-dialog").close(), 350);
    } catch (error) { status.textContent = error.message; }
}

function renderAlbums() {
    const page = pageItems(libraryState.filteredAlbums, "albums");
    const grid = document.getElementById("albums-grid");

    grid.innerHTML = page.items.length ? page.items.map((album) => `
        <button class="library-album-card" type="button" data-album="${escapeAttribute(album.album)}" data-album-key="${escapeAttribute(album.metadata_key)}">
            ${artwork(album.cover_url, "library-album-artwork")}
            <span class="library-album-copy">
                <strong title="${escapeAttribute(album.album)}">${escapeHtml(album.album || "Unknown album")}</strong>
                <span>${escapeHtml(album.artist || "Unknown artist")}</span>
                <small>${pluralize(album.track_count, "song")}</small>
            </span>
        </button>
    `).join("") : emptyGrid("No albums match your search.");

    grid.querySelectorAll("[data-album]").forEach((card) => {
        card.addEventListener("click", () => showSongsFor("album", card.dataset.album, card.dataset.albumKey));
    });
    renderPagination("pagination-albums", page, "albums", renderAlbums);
}

function renderArtists() {
    const page = pageItems(libraryState.filteredArtists, "artists");
    const grid = document.getElementById("artists-grid");

    grid.innerHTML = page.items.length ? page.items.map((artist) => `
        <button class="library-artist-card" type="button" data-artist="${escapeAttribute(artist.artist)}">
            <span class="library-artist-avatar">${icons.artist}</span>
            <span class="library-artist-copy">
                <strong>${escapeHtml(artist.artist || "Unknown artist")}</strong>
                <span><b>${Number(artist.album_count || 0).toLocaleString()}</b> ${pluralizeLabel(artist.album_count, "album")}</span>
                <span><b>${Number(artist.song_count || 0).toLocaleString()}</b> ${pluralizeLabel(artist.song_count, "song")}</span>
            </span>
            <span class="library-card-arrow" aria-hidden="true">›</span>
        </button>
    `).join("") : emptyGrid("No artists match your search.");

    grid.querySelectorAll("[data-artist]").forEach((card) => {
        card.addEventListener("click", () => showSongsFor("artist", card.dataset.artist));
    });
    renderPagination("pagination-artists", page, "artists", renderArtists);
}

function pageItems(items, key) {
    const totalPages = Math.max(1, Math.ceil(items.length / libraryState.pageSize));
    libraryState.pages[key] = Math.min(libraryState.pages[key], totalPages);
    const page = libraryState.pages[key];
    const start = (page - 1) * libraryState.pageSize;
    return { items: items.slice(start, start + libraryState.pageSize), page, totalPages, totalItems: items.length };
}

function renderPagination(containerId, page, key, render) {
    const container = document.getElementById(containerId);
    if (page.totalItems <= libraryState.pageSize) {
        container.innerHTML = page.totalItems ? `<span>${page.totalItems.toLocaleString()} items</span>` : "";
        return;
    }

    container.innerHTML = `
        <button class="btn-secondary" type="button" data-direction="previous" ${page.page === 1 ? "disabled" : ""}>Previous</button>
        <span>Page <b>${page.page}</b> of ${page.totalPages} · ${page.totalItems.toLocaleString()} items</span>
        <button class="btn-secondary" type="button" data-direction="next" ${page.page === page.totalPages ? "disabled" : ""}>Next</button>
    `;
    container.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
            libraryState.pages[key] += button.dataset.direction === "next" ? 1 : -1;
            render();
            document.querySelector(".library-panel").scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });
}

function switchView(view) {
    libraryState.view = view;
    document.querySelectorAll(".library-tab").forEach((tab) => {
        const active = tab.dataset.view === view;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
    });
    document.getElementById("library-sort").disabled = false;
    renderActiveView();
}

function showSongsFor(field, value, albumKey = null) {
    libraryState.query = value || "";
    document.getElementById("library-search").value = libraryState.query;
    applyFilters();
    if (field === "album") {
        libraryState.filteredSongs = libraryState.songs.filter((song) => (song.album || "") === value &&
            (!albumKey || libraryAlbumKey(song.album_artist || song.artist, song.album) === albumKey));
    } else {
        libraryState.filteredSongs = libraryState.songs.filter((song) => (song.artist || "") === value);
    }
    libraryState.pages.songs = 1;
    switchView("songs");
}

function artwork(url, className) {
    if (url) return `<img class="${className}" src="${escapeAttribute(url)}" alt="" loading="lazy">`;
    return `<span class="${className} library-artwork-placeholder">${icons.music}</span>`;
}

function formatDuration(seconds) {
    if (!Number.isFinite(Number(seconds))) return "—";
    const total = Math.round(Number(seconds));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatBitrate(bitrate) {
    if (!Number.isFinite(Number(bitrate)) || Number(bitrate) <= 0) return "—";
    return `${Math.round(Number(bitrate) / 1000)} kbps`;
}

function pluralize(count, noun) {
    const value = Number(count || 0);
    return `${value.toLocaleString()} ${pluralizeLabel(value, noun)}`;
}

function pluralizeLabel(count, noun) {
    return Number(count || 0) === 1 ? noun : `${noun}s`;
}

function emptyTable(message) {
    return `<tr><td colspan="6"><div class="library-empty">${icons.music}<strong>${escapeHtml(message)}</strong></div></td></tr>`;
}

function emptyGrid(message) {
    return `<div class="library-empty">${icons.music}<strong>${escapeHtml(message)}</strong></div>`;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, (character) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    })[character]);
}

function escapeAttribute(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
}

const bulkActions = {
    delete: {
        title: "Delete selected songs?",
        message: "This permanently removes the selected audio files. Their Library records remain available for missing-file detection.",
        confirm: "Delete files",
    },
    forget_missing: {
        title: "Forget selected missing records?",
        message: "This permanently removes the selected canonical Library records and their missing-file health warnings. No audio or artwork files will be deleted.",
        confirm: "Forget records",
    },
    move: {
        title: "Move selected songs?",
        message: "Each song keeps its filename and Library identity.",
        confirm: "Move songs",
        label: "Destination folder",
        placeholder: "Organized/Favorites",
        help: "Enter a folder relative to Harmony's music folder.",
    },
    rename: {
        title: "Rename selected songs?",
        message: "Harmony applies the pattern separately to every selected song.",
        confirm: "Rename songs",
        label: "Filename pattern",
        placeholder: "{track} - {title}{ext}",
        value: "{track} - {title}{ext}",
        help: "Available: {artist}, {album}, {title}, {track}, {disc}, {filename}, {ext}.",
    },
    refresh_metadata: {
        title: "Refresh metadata?",
        message: "Harmony will re-read tags and technical audio properties from every selected file.",
        confirm: "Refresh metadata",
    },
    refresh_artwork: {
        title: "Refresh artwork cache?",
        message: "Harmony will re-read embedded and folder artwork and repair local cache associations.",
        confirm: "Refresh artwork",
    },
    fetch_artwork: {
        title: "Fetch album art?",
        message: "Harmony will download and cache canonical artwork using a MusicBrainz release ID or a linked YouTube Music track. Songs without a supported source identity will be skipped with an explanation.",
        confirm: "Fetch album art",
    },
    export: {
        title: "Export selected songs?",
        message: "Harmony will create a ZIP archive in the background and provide a download when it is ready.",
        confirm: "Create export",
    },
};

function currentSongPage() {
    return pageItems(libraryState.filteredSongs, "songs").items;
}

function updateBulkSelection(pageSongs = currentSongPage()) {
    const count = libraryState.selectedSongs.size;
    document.getElementById("library-selected-count").textContent = count.toLocaleString();
    document.getElementById("library-bulk-toolbar").hidden = count === 0;
    const selectedOnPage = pageSongs.filter((song) => libraryState.selectedSongs.has(song.id)).length;
    const selectPage = document.getElementById("library-select-page");
    selectPage.checked = pageSongs.length > 0 && selectedOnPage === pageSongs.length;
    selectPage.indeterminate = selectedOnPage > 0 && selectedOnPage < pageSongs.length;
    updateMobileSelectAll();
}

function updateMobileSelectAll() {
    const button = document.getElementById("library-select-all-mobile");
    if (!button) return;
    const visibleSongs = libraryState.filteredSongs;
    const available = libraryState.view === "songs" && visibleSongs.length > 0;
    button.hidden = !available;
    if (!available) return;
    const allSelected = visibleSongs.every((song) => libraryState.selectedSongs.has(song.id));
    button.textContent = allSelected
        ? "Clear selection"
        : `Select all (${visibleSongs.length.toLocaleString()})`;
    button.setAttribute("aria-pressed", String(allSelected));
}

function clearBulkSelection() {
    libraryState.selectedSongs.clear();
    renderSongs();
}

function showBulkDialog(operation) {
    const action = bulkActions[operation];
    const dialog = document.getElementById("library-bulk-dialog");
    const optionWrap = document.getElementById("library-bulk-option-wrap");
    const option = document.getElementById("library-bulk-option");
    dialog.dataset.operation = operation;
    document.getElementById("library-bulk-dialog-title").textContent = action.title;
    document.getElementById("library-bulk-dialog-message").textContent =
        `${action.message} ${pluralize(libraryState.selectedSongs.size, "song")} selected.`;
    document.getElementById("library-bulk-confirm").textContent = action.confirm;
    document.getElementById("library-bulk-confirm").classList.toggle(
        "library-danger-button",
        ["delete", "forget_missing"].includes(operation),
    );
    optionWrap.hidden = !action.label;
    if (action.label) {
        document.getElementById("library-bulk-option-label").textContent = action.label;
        document.getElementById("library-bulk-option-help").textContent = action.help || "";
        option.placeholder = action.placeholder || "";
        option.value = action.value || "";
        option.required = true;
    } else {
        option.required = false;
        option.value = "";
    }
    dialog.showModal();
    if (action.label) option.focus();
}

async function startBulkOperation(operation, optionValue) {
    const options = {};
    if (operation === "move") options.destination = optionValue;
    if (operation === "rename") options.pattern = optionValue;
    const response = await fetch("/api/library/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation, song_ids: [...libraryState.selectedSongs], options }),
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Request failed: ${response.status}`);
    }
    const task = await response.json();
    libraryState.bulkTaskId = task.id;
    renderBulkProgress(task);
    pollBulkTask();
}

async function pollBulkTask() {
    clearTimeout(libraryState.bulkPollTimer);
    if (!libraryState.bulkTaskId) return;
    try {
        const task = await fetchJson(`/api/library/bulk/${libraryState.bulkTaskId}`);
        renderBulkProgress(task);
        if (["completed", "failed", "cancelled"].includes(task.status)) {
            libraryState.selectedSongs.clear();
            await loadLibraryData({ preserveState: true });
            return;
        }
        libraryState.bulkPollTimer = setTimeout(pollBulkTask, 700);
    } catch (error) {
        document.getElementById("library-bulk-progress-detail").textContent =
            "Progress is temporarily unavailable. Retrying…";
        libraryState.bulkPollTimer = setTimeout(pollBulkTask, 1500);
    }
}

function renderBulkProgress(task) {
    const panel = document.getElementById("library-bulk-progress");
    const terminal = ["completed", "failed", "cancelled"].includes(task.status);
    panel.hidden = false;
    document.getElementById("library-bulk-progress-title").textContent = task.name;
    document.getElementById("library-bulk-progress-count").textContent = `${task.processed} of ${task.total}`;
    document.getElementById("library-bulk-progress-bar").value = task.progress;
    const detail = terminal
        ? `${task.completed} completed · ${task.failed} failed · ${task.skipped} cancelled`
        : task.current ? `Processing ${task.current}` : "Queued for background processing…";
    document.getElementById("library-bulk-progress-detail").textContent = detail;
    document.getElementById("library-bulk-cancel").hidden = terminal;
    document.getElementById("library-bulk-dismiss").hidden = !terminal;
    const download = document.getElementById("library-bulk-download");
    download.hidden = !terminal || !task.download_url;
    if (task.download_url) download.href = task.download_url;
}

document.querySelectorAll(".library-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
});

document.getElementById("library-select-page").addEventListener("change", (event) => {
    currentSongPage().forEach((song) => {
        event.target.checked ? libraryState.selectedSongs.add(song.id) : libraryState.selectedSongs.delete(song.id);
    });
    renderSongs();
});
document.getElementById("library-duplicates-open").addEventListener("click", openDuplicateReview);
document.getElementById("duplicate-review-close").addEventListener("click", () => document.getElementById("duplicate-review-dialog").close());
document.getElementById("duplicate-tier").addEventListener("change", loadDuplicateCandidates);

document.getElementById("library-clear-selection").addEventListener("click", clearBulkSelection);
document.getElementById("library-select-all-mobile").addEventListener("click", () => {
    const visibleSongs = libraryState.filteredSongs;
    if (!visibleSongs.length) return;
    const allSelected = visibleSongs.every((song) => libraryState.selectedSongs.has(song.id));
    if (allSelected) {
        libraryState.selectedSongs.clear();
    } else {
        visibleSongs.forEach((song) => libraryState.selectedSongs.add(song.id));
    }
    renderSongs();
});
document.querySelectorAll("[data-bulk-action]").forEach((button) => {
    button.addEventListener("click", () => showBulkDialog(button.dataset.bulkAction));
});

document.getElementById("library-bulk-confirm").addEventListener("click", async (event) => {
    event.preventDefault();
    const dialog = document.getElementById("library-bulk-dialog");
    const option = document.getElementById("library-bulk-option");
    if (option.required && !option.value.trim()) {
        option.reportValidity();
        return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    try {
        await startBulkOperation(dialog.dataset.operation, option.value.trim());
        dialog.close();
    } catch (error) {
        document.getElementById("library-bulk-dialog-message").textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

document.getElementById("library-bulk-cancel").addEventListener("click", async () => {
    if (!libraryState.bulkTaskId) return;
    await fetch(`/api/library/bulk/${libraryState.bulkTaskId}/cancel`, { method: "POST" });
    pollBulkTask();
});

document.getElementById("library-bulk-dismiss").addEventListener("click", () => {
    document.getElementById("library-bulk-progress").hidden = true;
    libraryState.bulkTaskId = null;
});

document.getElementById("library-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
        libraryState.query = event.target.value;
        Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
        performSearch();
    }, 180);
});
document.querySelectorAll("[data-search-example]").forEach((button) => {
    button.addEventListener("click", () => {
        const input = document.getElementById("library-search");
        input.value = button.dataset.searchExample;
        libraryState.query = input.value;
        Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
        performSearch();
        input.focus();
    });
});

document.getElementById("library-sort").addEventListener("change", (event) => {
    libraryState.sort = event.target.value;
    libraryState.pages.songs = 1;
    saveLibraryPreferences();
    loadLibraryData({ preserveState: true });
});

document.getElementById("library-filter-toggle").addEventListener("click", () => {
    libraryState.filterPanelOpen = !libraryState.filterPanelOpen;
    saveLibraryPreferences();
    updateFilterControls();
});

["artist", "album", "genre", "codec", "bitrate"].forEach((field) => {
    document.getElementById(`filter-${field}`).addEventListener("change", (event) => {
        libraryState.filters[field] = event.target.value;
        Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
        saveLibraryPreferences();
        loadLibraryData({ preserveState: true });
    });
});

["downloaded_today", "recently_added", "missing_artwork", "missing_metadata"].forEach((field) => {
    document.getElementById(`filter-${field.replaceAll("_", "-")}`).addEventListener("change", (event) => {
        libraryState.filters[field] = event.target.checked;
        Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
        saveLibraryPreferences();
        loadLibraryData({ preserveState: true });
    });
});

document.getElementById("clear-library-filters").addEventListener("click", () => {
    Object.assign(libraryState.filters, {
        artist: "",
        album: "",
        genre: "",
        codec: "",
        bitrate: "",
        downloaded_today: false,
        recently_added: false,
        missing_artwork: false,
        missing_metadata: false,
    });
    Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
    saveLibraryPreferences();
    updateFilterControls();
    loadLibraryData({ preserveState: true });
});


document.getElementById("btn-rescan").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span><span>Rescanning…</span>`;
    try {
        const response = await fetch("/api/library/rescan", { method: "POST" });
        if (!response.ok) throw new Error("Rescan failed");
        await loadLibraryData({ preserveState: true });
    } catch (error) {
        document.getElementById("library-error").textContent = "The library rescan failed. Check Harmony logs for details.";
        document.getElementById("library-error").hidden = false;
    } finally {
        button.disabled = false;
        button.innerHTML = original;
    }
});

function connectLibraryEvents() {
    if (!("EventSource" in window)) return;
    const events = new EventSource("/api/library/events");
    ["library.track.added", "library.track.updated", "library.track.missing", "library.track.renamed", "library.track.forgotten"].forEach((type) => {
        events.addEventListener(type, () => {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(() => loadLibraryData({ preserveState: true }), 500);
        });
    });
}

async function uploadRequest(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let message = `Request failed: ${response.status}`;
        try {
            const payload = await response.json();
            message = typeof payload.detail === "string" ? payload.detail : payload.detail?.message || message;
        } catch (_) { /* Use the bounded status message. */ }
        throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
}

function uploadField(item, field, label, type = "text") {
    const value = item.proposed[field] ?? "";
    const limits = type === "number" ? ' min="0" max="9999"' : ' maxlength="500"';
    return `<label>${label}<input data-upload-field="${field}" type="${type}" value="${escapeHtml(String(value))}"${limits}></label>`;
}

function renderUploadReview() {
    const review = document.getElementById("library-upload-review");
    review.innerHTML = libraryUploadState.items.map((item) => {
        const duplicate = libraryUploadState.duplicates?.items?.find((entry) => entry.item_id === item.id);
        const findings = [
            ...item.changes.map((change) => `${change.field}: “${change.before || ""}” → “${change.after || "removed"}”`),
            ...item.warnings,
        ];
        return `<article class="library-upload-item" data-upload-item="${item.id}">
            <input data-upload-selected type="checkbox" ${duplicate?.recommended_action === "skip" ? "" : "checked"} aria-label="Import ${escapeHtml(item.original_name)}">
            <div>
                <strong>${escapeHtml(item.original_name)}</strong>
                <div class="library-upload-item-fields">
                    ${uploadField(item, "title", "Title")}${uploadField(item, "artist", "Artist")}
                    ${uploadField(item, "album_artist", "Album artist")}${uploadField(item, "album", "Album")}
                    ${uploadField(item, "genre", "Genre")}${uploadField(item, "year", "Year", "number")}
                    ${uploadField(item, "track", "Track", "number")}${uploadField(item, "disc", "Disc", "number")}
                </div>
                <p class="library-upload-findings">${findings.length ? `<strong>Review:</strong> ${escapeHtml(findings.join(" · "))}` : "No obvious download-site branding detected."}</p>
                <small class="library-upload-destination">Proposed location: ${escapeHtml(item.destination)}</small>
                ${duplicate ? `<div class="library-upload-duplicates"><strong>${duplicate.matches.length} existing Library ${duplicate.matches.length === 1 ? "match" : "matches"} · ${duplicate.recommended_action === "skip" ? "Skipped by default" : "Review before importing"}</strong>${duplicate.matches.map((match) => `<div><span class="duplicate-tier-badge">${escapeHtml(match.tier)}</span> ${escapeHtml(match.title || match.filename)} — ${escapeHtml(match.artist || "Unknown artist")} <small>${escapeHtml(match.evidence)}</small></div>`).join("")}</div>` : ""}
            </div>
        </article>`;
    }).join("");
    document.getElementById("library-upload-import").disabled = !libraryUploadState.items.length;
    renderUploadAlbumReview();
}

function selectedUploadAlbumGroup() {
    const id = document.getElementById("library-upload-album-group").value;
    return libraryUploadState.summary?.groups?.find((group) => group.id === id) || null;
}

function populateUploadAlbumFields() {
    const group = selectedUploadAlbumGroup();
    if (!group) return;
    document.getElementById("library-upload-album").value = group.values.album || "";
    document.getElementById("library-upload-album-artist").value = group.values.album_artist || "";
    document.getElementById("library-upload-album-genre").value = group.values.genre || "";
    document.getElementById("library-upload-album-year").value = group.values.year ?? "";
    document.getElementById("library-upload-album-findings").textContent = group.findings.length
        ? group.findings.join(" · ") : "This group has consistent shared album metadata and track numbering.";
    const preview = document.getElementById("library-upload-album-artwork-preview");
    preview.src = group.artwork?.url || "";
    preview.hidden = !group.artwork?.url;
    document.getElementById("library-upload-album-artwork-remove").hidden = !group.artwork;
    document.getElementById("library-upload-album-matches").innerHTML = "";
}

function renderUploadAlbumReview() {
    const section = document.getElementById("library-upload-album-review");
    const groups = libraryUploadState.summary?.groups || [];
    section.hidden = !groups.length;
    if (!groups.length) return;
    const select = document.getElementById("library-upload-album-group");
    const previous = select.value;
    select.innerHTML = groups.map((group) => `<option value="${group.id}">${escapeHtml(group.label)} · ${group.track_count} ${group.track_count === 1 ? "track" : "tracks"}</option>`).join("");
    if (groups.some((group) => group.id === previous)) select.value = previous;
    document.getElementById("library-upload-album-summary").textContent = `${groups.length} ${groups.length === 1 ? "group" : "groups"} · ${libraryUploadState.summary.finding_count} findings`;
    populateUploadAlbumFields();
}

function applyUploadAlbumMetadata() {
    const group = selectedUploadAlbumGroup();
    if (!group) return;
    const values = {
        album: document.getElementById("library-upload-album").value.trim(),
        album_artist: document.getElementById("library-upload-album-artist").value.trim(),
        genre: document.getElementById("library-upload-album-genre").value.trim(),
        year: document.getElementById("library-upload-album-year").value,
    };
    group.item_ids.forEach((itemId) => {
        const row = document.querySelector(`[data-upload-item="${itemId}"]`);
        if (!row) return;
        Object.entries(values).forEach(([field, value]) => {
            const input = row.querySelector(`[data-upload-field="${field}"]`);
            if (input) input.value = value;
        });
    });
    document.getElementById("library-upload-album-findings").textContent = `Applied shared metadata to ${group.item_ids.length} ${group.item_ids.length === 1 ? "track" : "tracks"}. Review individual titles and track numbers below.`;
}

async function searchUploadAlbumMetadata() {
    const group = selectedUploadAlbumGroup();
    if (!group) return;
    const target = document.getElementById("library-upload-album-matches");
    const album = document.getElementById("library-upload-album").value.trim();
    const artist = document.getElementById("library-upload-album-artist").value.trim();
    target.textContent = "Searching MusicBrainz…";
    try {
        const result = await uploadRequest(`/api/library/metadata/search?album=${encodeURIComponent(album)}&artist=${encodeURIComponent(artist)}`);
        const unique = [...new Map(result.items.filter((item) => item.release_id).map((item) => [item.release_id, item])).values()];
        target.innerHTML = unique.map((item) => `<article class="metadata-suggestion-card"><strong>${escapeHtml(item.album || item.title || "Unknown release")}</strong><small>${escapeHtml(item.album_artist || item.artist || "Unknown artist")} · ${item.year || "Year unknown"}</small><button type="button" class="btn-secondary" data-upload-album-match="${item.release_id}">Use release</button></article>`).join("") || "No matching releases found.";
        target.querySelectorAll("[data-upload-album-match]").forEach((button) => button.addEventListener("click", () => applyUploadAlbumMatch(unique.find((item) => item.release_id === button.dataset.uploadAlbumMatch))));
    } catch (error) { target.textContent = error.message; }
}

async function applyUploadAlbumMatch(match) {
    if (!match) return;
    document.getElementById("library-upload-album").value = match.album || "";
    document.getElementById("library-upload-album-artist").value = match.album_artist || match.artist || "";
    document.getElementById("library-upload-album-year").value = match.year ?? "";
    applyUploadAlbumMetadata();
    const group = selectedUploadAlbumGroup();
    try {
        const updated = await uploadRequest(`/api/library/uploads/batches/${libraryUploadState.batchId}/groups/${group.id}/artwork/musicbrainz?release_id=${encodeURIComponent(match.release_id)}`, {method:"POST"});
        group.artwork = updated.artwork;
        populateUploadAlbumFields();
    } catch (error) { document.getElementById("library-upload-album-findings").textContent = `Metadata applied. Artwork was unavailable: ${error.message}`; }
}

async function uploadAlbumArtwork(file) {
    const group = selectedUploadAlbumGroup(); if (!group || !file) return;
    const form = new FormData(); form.append("file", file, file.name);
    try { const updated = await uploadRequest(`/api/library/uploads/batches/${libraryUploadState.batchId}/groups/${group.id}/artwork`, {method:"POST",body:form}); group.artwork=updated.artwork; populateUploadAlbumFields(); }
    catch(error){ document.getElementById("library-upload-album-findings").textContent=error.message; }
}

async function removeAlbumArtwork() {
    const group=selectedUploadAlbumGroup(); if(!group)return;
    await uploadRequest(`/api/library/uploads/batches/${libraryUploadState.batchId}/groups/${group.id}/artwork`,{method:"DELETE"}); group.artwork=null; populateUploadAlbumFields();
}

async function ensureUploadBatch() {
    if (libraryUploadState.batchId) return libraryUploadState.batchId;
    const batch = await uploadRequest("/api/library/uploads/batches", {method: "POST"});
    libraryUploadState.batchId = batch.id;
    document.getElementById("library-upload-discard").hidden = false;
    saveUploadRecovery();
    return batch.id;
}

function saveUploadRecovery() {
    try {
        if (!libraryUploadState.batchId && !libraryUploadState.taskId) localStorage.removeItem(LIBRARY_UPLOAD_RECOVERY_KEY);
        else localStorage.setItem(LIBRARY_UPLOAD_RECOVERY_KEY, JSON.stringify({batchId:libraryUploadState.batchId,taskId:libraryUploadState.taskId}));
    } catch (_) {}
}

async function loadUploadBatch(batchId) {
    const batch=await uploadRequest(`/api/library/uploads/batches/${batchId}`);
    libraryUploadState.batchId=batch.id; libraryUploadState.items=batch.items; libraryUploadState.summary=batch.summary; libraryUploadState.duplicates=batch.duplicates;
    document.getElementById("library-upload-discard").hidden=false; renderUploadReview(); saveUploadRecovery(); return batch;
}

async function monitorUploadTask(task) {
    const status=document.getElementById("library-upload-status"); libraryUploadState.taskId=task.id; saveUploadRecovery();
    document.getElementById("library-upload-cancel").hidden=false; document.getElementById("library-upload-discard").hidden=true;
    let progress=task;
    while(["queued","running","cancelling"].includes(progress.status)){
        status.textContent=`${progress.status.replaceAll("_"," ")} · ${progress.processed}/${progress.total}${progress.current?` · ${progress.current}`:""}`;
        await new Promise((resolve)=>setTimeout(resolve,700)); progress=await uploadRequest(`/api/tasks/jobs/${task.id}`);
    }
    status.textContent=`${progress.status.replaceAll("_"," ")} · ${progress.completed} imported · ${progress.failed} failed · ${progress.skipped} skipped${progress.error_summary?` · ${progress.error_summary}`:""}`;
    libraryUploadState.taskId=null; document.getElementById("library-upload-cancel").hidden=true;
    try{await loadUploadBatch(libraryUploadState.batchId);}catch(_){libraryUploadState.items=[];libraryUploadState.batchId=null;libraryUploadState.summary=null;libraryUploadState.duplicates=null;document.getElementById("library-upload-discard").hidden=true;renderUploadReview();}
    saveUploadRecovery(); await loadLibraryData({preserveState:true});
}

async function restoreLocalUpload() {
    if(libraryUploadState.taskId||libraryUploadState.batchId)return;
    let saved={}; try{saved=JSON.parse(localStorage.getItem(LIBRARY_UPLOAD_RECOVERY_KEY)||"{}");}catch(_){}
    if(saved.taskId){try{const task=await uploadRequest(`/api/tasks/jobs/${saved.taskId}`); if(["queued","running","cancelling"].includes(task.status)){libraryUploadState.batchId=saved.batchId; monitorUploadTask(task).catch((error)=>{document.getElementById("library-upload-status").textContent=error.message;}); return;}}catch(_){} }
    try{
        const listing=await uploadRequest("/api/library/uploads/batches"); const candidate=listing.items.find((item)=>item.id===saved.batchId)||listing.items[0];
        if(candidate){await loadUploadBatch(candidate.id); document.getElementById("library-upload-status").textContent=`Restored ${candidate.item_count} staged ${candidate.item_count===1?"file":"files"}. Batch expires ${new Date(candidate.expires_at*1000).toLocaleString()}.`; if(candidate.task&&["queued","running","cancelling"].includes(candidate.task.status))monitorUploadTask(candidate.task).catch((error)=>{document.getElementById("library-upload-status").textContent=error.message;});}
    }catch(_){}
}

async function discardLocalUpload() {
    if(!libraryUploadState.batchId||libraryUploadState.taskId)return;
    await uploadRequest(`/api/library/uploads/batches/${libraryUploadState.batchId}`,{method:"DELETE"});
    libraryUploadState.batchId=null;libraryUploadState.items=[];libraryUploadState.summary=null;libraryUploadState.duplicates=null;saveUploadRecovery();renderUploadReview();document.getElementById("library-upload-discard").hidden=true;document.getElementById("library-upload-status").textContent="Staged batch discarded.";
}

async function stageLocalFiles(files) {
    if (!files.length) return;
    const status = document.getElementById("library-upload-status");
    const input = document.getElementById("library-upload-files");
    status.textContent = `Uploading and inspecting ${files.length} ${files.length === 1 ? "file" : "files"}…`;
    input.disabled = true;
    try {
        const batchId = await ensureUploadBatch();
        const form = new FormData();
        [...files].forEach((file) => form.append("files", file, file.name));
        const result = await uploadRequest(`/api/library/uploads/batches/${batchId}/files`, {method: "POST", body: form});
        libraryUploadState.items.push(...result.items);
        libraryUploadState.summary = result.summary;
        libraryUploadState.duplicates = result.duplicates;
        renderUploadReview();
        const failures = result.errors?.length ? ` ${result.errors.length} rejected: ${result.errors.map((item) => `${item.filename}: ${item.error}`).join("; ")}` : "";
        status.textContent = `${libraryUploadState.items.length} staged. Review cleanup and metadata before importing.${failures}`;
    } catch (error) {
        status.textContent = error.message;
    } finally {
        input.disabled = false;
        input.value = "";
    }
}

function selectedUploadItems() {
    return [...document.querySelectorAll("[data-upload-item]")].filter((row) => row.querySelector("[data-upload-selected]").checked).map((row) => {
        const metadata = {};
        row.querySelectorAll("[data-upload-field]").forEach((input) => {
            metadata[input.dataset.uploadField] = input.type === "number"
                ? (input.value === "" ? null : Number(input.value)) : input.value.trim() || null;
        });
        return {id: row.dataset.uploadItem, metadata};
    });
}

async function importLocalFiles() {
    const items = selectedUploadItems();
    const status = document.getElementById("library-upload-status");
    if (!items.length) { status.textContent = "Select at least one file to import."; return; }
    const button = document.getElementById("library-upload-import");
    button.disabled = true;
    status.textContent = `Cleaning, verifying, and importing ${items.length} ${items.length === 1 ? "file" : "files"}…`;
    try {
        const task = await uploadRequest(`/api/library/uploads/batches/${libraryUploadState.batchId}/import`, {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({items, scan_navidrome: document.getElementById("library-upload-scan").checked}),
        });
        await monitorUploadTask(task);
    } catch (error) {
        status.textContent = error.message;
    } finally {
        button.disabled = !libraryUploadState.items.length;
    }
}

async function closeLocalUpload() {
    document.getElementById("library-upload-dialog").close();
    saveUploadRecovery();
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("library-upload-open").addEventListener("click", async () => { await restoreLocalUpload(); document.getElementById("library-upload-dialog").showModal(); });
    document.getElementById("library-upload-close").addEventListener("click", closeLocalUpload);
    document.getElementById("library-upload-files").addEventListener("change", (event) => stageLocalFiles(event.target.files));
    document.getElementById("library-upload-import").addEventListener("click", importLocalFiles);
    document.getElementById("library-upload-cancel").addEventListener("click", async () => { if (libraryUploadState.taskId) await fetch(`/api/tasks/jobs/${libraryUploadState.taskId}/cancel`, {method:"POST"}); });
    document.getElementById("library-upload-discard").addEventListener("click", discardLocalUpload);
    document.getElementById("library-upload-album-group").addEventListener("change", populateUploadAlbumFields);
    document.getElementById("library-upload-album-apply").addEventListener("click", applyUploadAlbumMetadata);
    document.getElementById("library-upload-album-search").addEventListener("click", searchUploadAlbumMetadata);
    document.getElementById("library-upload-album-artwork-file").addEventListener("change", (event) => uploadAlbumArtwork(event.target.files[0]));
    document.getElementById("library-upload-album-artwork-remove").addEventListener("click", removeAlbumArtwork);
    const uploadDrop = document.getElementById("library-upload-drop");
    ["dragenter", "dragover"].forEach((name) => uploadDrop.addEventListener(name, (event) => { event.preventDefault(); uploadDrop.classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach((name) => uploadDrop.addEventListener(name, (event) => { event.preventDefault(); uploadDrop.classList.remove("is-dragging"); }));
    uploadDrop.addEventListener("drop", (event) => stageLocalFiles(event.dataTransfer.files));
    document.getElementById("metadata-search-button").addEventListener("click", searchMetadata);
    document.getElementById("metadata-editor-form").addEventListener("submit", saveMetadata);
    ["metadata-editor-close", "metadata-editor-cancel"].forEach((id) => document.getElementById(id).addEventListener("click", () => document.getElementById("metadata-editor-dialog").close()));
    document.getElementById("metadata-artwork-file").addEventListener("change", (event) => { const file = event.target.files[0]; if (file) { metadataEditorArtworkRelease = null; document.getElementById("metadata-artwork-preview").src = URL.createObjectURL(file); } });
    const params = new URLSearchParams(window.location.search);
    const requestedView = params.get("view");
    const requestedAlbumKey = params.get("album_key");
    const requestedSongId = Number(params.get("song"));
    const requestedAvailability = params.get("availability");
    if (requestedAlbumKey) {
        libraryState.requestedAlbumKey = requestedAlbumKey;
        Object.assign(libraryState.filters, { artist: "", album: "", genre: "", codec: "", bitrate: "", downloaded_today: false, recently_added: false, missing_artwork: false, missing_metadata: false });
    }
    if (["songs", "albums", "artists"].includes(requestedView)) libraryState.view = requestedView;
    if (Number.isInteger(requestedSongId) && requestedSongId > 0) {
        libraryState.requestedSongId = requestedSongId;
        libraryState.view = "songs";
    }
    if (requestedAvailability === "missing") {
        libraryState.requestedAvailability = requestedAvailability;
        libraryState.view = "songs";
        document.getElementById("library-bulk-delete").hidden = true;
        document.getElementById("library-bulk-forget-missing").hidden = false;
    }
    document.getElementById("library-sort").value = libraryState.sort;
    updateFilterControls();
    switchView(libraryState.view);
    loadLibraryData();
    connectLibraryEvents();
    restoreLocalUpload();
});
