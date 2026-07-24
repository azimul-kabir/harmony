const LIBRARY_PREFERENCES_KEY = "harmony.library.preferences.v1";
const DEFAULT_BITRATE_RANGES = {
    lossless: { min: 900000, max: null },
    high: { min: 320000, max: null },
    standard: { min: 192000, max: 319999 },
    compact: { min: null, max: 191999 },
};
const DEFAULT_COLLECTIONS = [
    ["recently-added", "Recently Added", "Music added to the Library Index during the last seven days.", "blue", "recent"],
    ["recently-downloaded", "Recently Downloaded", "Downloads added during the last seven days.", "cyan", "download"],
    ["highest-bitrate", "Highest Bitrate", "Tracks at the highest bitrate currently in the Library.", "violet", "quality"],
    ["missing-artwork", "Missing Artwork", "Tracks that still need a local artwork resource.", "amber", "artwork"],
    ["missing-metadata", "Missing Metadata", "Tracks missing a title, artist, or album.", "rose", "metadata"],
    ["recently-modified", "Recently Modified", "Files modified during the last seven days.", "green", "modified"],
    ["large-albums", "Large Albums", "Tracks from albums containing at least ten indexed songs.", "indigo", "album"],
    ["favorites", "Favorites", "Ready for a future favorites signal.", "pink", "favorite", true],
].map(([id, name, description, tone, icon, placeholder = false]) => ({
    id, name, description, tone, icon, placeholder, song_count: 0,
}));
const savedPreferences = readLibraryPreferences();

const libraryState = {
    songs: [],
    albums: [],
    artists: [],
    collections: [],
    filterOptions: null,
    analytics: null,
    filteredSongs: [],
    filteredAlbums: [],
    filteredArtists: [],
    filteredCollections: [],
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
    requestedMetadataReviewSongId: null,
    requestedAvailability: null,
    collectionId: null,
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
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
}

async function loadAnalytics() {
    try {
        libraryState.analytics = await fetchJson("/api/library/analytics");
        renderAnalytics(libraryState.analytics);
    } catch (error) {
        console.error("Library analytics error:", error);
        document.getElementById("analytics-updated").textContent = "Analytics unavailable";
    }
}

function renderAnalytics(analytics) {
    const values = {
        songs: Number(analytics.songs || 0).toLocaleString(),
        albums: Number(analytics.albums || 0).toLocaleString(),
        artists: Number(analytics.artists || 0).toLocaleString(),
        genres: Number(analytics.genres || 0).toLocaleString(),
        storage: formatBytes(analytics.storage_bytes),
        bitrate: formatBitrate(analytics.average_bitrate),
        duration: formatDuration(analytics.average_duration),
        recent: Number(analytics.recently_added || 0).toLocaleString(),
    };
    Object.entries(values).forEach(([key, value]) => {
        document.getElementById(`analytics-${key}`).textContent = value;
    });
    renderAlbumInsight("largest", analytics.largest_album, (album) =>
        `${album.artist} · ${pluralize(album.song_count, "song")} · ${formatBytes(album.storage_bytes)}`);
    renderAlbumInsight("newest", analytics.newest_album, (album) =>
        `${album.artist} · ${album.year || "Year unknown"}`);
    renderAlbumInsight("oldest", analytics.oldest_album, (album) =>
        `${album.artist} · ${album.year || "Year unknown"}`);
    document.getElementById("analytics-updated").textContent = "Live from the Library Index";
}

function renderAlbumInsight(key, album, detail) {
    document.getElementById(`analytics-${key}-name`).textContent = album?.name || "—";
    document.getElementById(`analytics-${key}-detail`).textContent = album
        ? detail(album)
        : "No album data";
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
        const songEndpoint = libraryState.collectionId
            ? `/api/library/collections/${encodeURIComponent(libraryState.collectionId)}/songs`
            : "/api/library/songs";
        // Songs are the source for the Songs, Albums, and Artists views. Do
        // not let auxiliary collections or filter-options requests hide all
        // three views when one of those optional endpoints is unavailable.
        const songResult = await fetchJson(`${songEndpoint}?${libraryRequestParams()}`);
        const [collectionsResult, filterOptionsResult] = await Promise.allSettled([
            fetchJson("/api/library/collections"),
            libraryState.filterOptions
                ? Promise.resolve(libraryState.filterOptions)
                : fetchJson("/api/library/filter-options"),
        ]);

        const songs = Array.isArray(songResult) ? songResult : songResult.items;
        const { albums, artists } = projectSongs(songs);
        const collections = collectionsResult.status === "fulfilled"
            ? collectionsResult.value
            : DEFAULT_COLLECTIONS;
        const filterOptions = filterOptionsResult.status === "fulfilled"
            ? filterOptionsResult.value
            : libraryState.filterOptions;
        Object.assign(libraryState, { songs, albums, artists, collections, filterOptions });
        if (collectionsResult.status === "rejected") {
            console.error("Library collections error:", collectionsResult.reason);
        }
        if (filterOptionsResult.status === "rejected") {
            console.error("Library filter options error:", filterOptionsResult.reason);
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
        if (libraryState.requestedMetadataReviewSongId) {
            const songId = libraryState.requestedMetadataReviewSongId;
            libraryState.requestedMetadataReviewSongId = null;
            await openMetadataReview(songId);
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
    let songs = libraryState.songs.filter(songMatchesCollection);

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
    libraryState.filteredCollections = libraryState.collections.filter((collection) => !query ||
        [collection.name, collection.description].some((value) => String(value || "").toLocaleLowerCase().includes(query)));
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
        libraryState.filteredSongs = result.items.filter(songMatchesCollection);
        const projections = projectSongs(result.items);
        libraryState.filteredAlbums = projections.albums;
        libraryState.filteredArtists = projections.artists;
        libraryState.filteredCollections = libraryState.collections.filter((collection) =>
            [collection.name, collection.description].some((value) =>
                String(value || "").toLocaleLowerCase().includes(query.toLocaleLowerCase())));

        const shown = result.items.length;
        status.textContent = result.total > shown
            ? `${result.total.toLocaleString()} matches · showing first ${shown.toLocaleString()}`
            : `${result.total.toLocaleString()} ${result.total === 1 ? "match" : "matches"}`;
        renderActiveView();
    } catch (error) {
        if (request !== libraryState.searchRequest) return;
        console.error("Library search error:", error);
        status.textContent = "Search unavailable";
        const errorBox = document.getElementById("library-error");
        errorBox.textContent = "Harmony could not search the Library Index. Try again in a moment.";
        errorBox.hidden = false;
    }
}

function songMatchesCollection(song) {
    return true;
}

function updateCounts() {
    document.getElementById("songs-count").textContent = libraryState.songs.length.toLocaleString();
    document.getElementById("albums-count").textContent = libraryState.albums.length.toLocaleString();
    document.getElementById("artists-count").textContent = libraryState.artists.length.toLocaleString();
    document.getElementById("collections-count").textContent = libraryState.collections.length.toLocaleString();
}

function renderActiveView() {
    document.querySelectorAll(".library-view").forEach((view) => {
        view.hidden = view.id !== `view-${libraryState.view}`;
    });

    if (libraryState.view === "songs") renderSongs();
    if (libraryState.view === "albums") renderAlbums();
    if (libraryState.view === "artists") renderArtists();
    if (libraryState.view === "collections") renderCollections();
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
                <td data-label="Metadata"><button class="btn-secondary metadata-review-open" type="button" data-review-song="${song.id}">Review</button></td>
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
    body.querySelectorAll("[data-review-song]").forEach((button) => {
        button.addEventListener("click", () => openMetadataReview(Number(button.dataset.reviewSong)));
    });
    updateBulkSelection(page.items);

    renderPagination("pagination-songs", page, "songs", renderSongs);
}

function metadataValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function evidenceText(value) {
    if (value === null || value === undefined) return "None recorded";
    if (Array.isArray(value)) return value.map(metadataValue).join(" · ") || "None recorded";
    if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${metadataValue(item)}`).join(" · ");
    return String(value);
}

async function openMetadataReview(songId) {
    const dialog = document.getElementById("metadata-review-dialog");
    dialog.dataset.songId = String(songId);
    dialog.showModal();
    document.getElementById("metadata-discover").onclick = () => discoverMetadataMatch(songId);
    document.getElementById("metadata-select-eligible").onclick = () => document.querySelectorAll("[data-accepted-field]:not(:disabled)").forEach((item) => { item.checked = true; });
    document.getElementById("metadata-clear-selection").onclick = () => document.querySelectorAll("[data-accepted-field]").forEach((item) => { item.checked = false; });
    document.getElementById("metadata-preview-accepted").onclick = () => previewMetadataApplication(songId);
    document.getElementById("metadata-apply-selected").onclick = () => submitMetadataApplication(songId, false);
    document.getElementById("metadata-apply-accepted").onclick = () => submitMetadataApplication(songId, true);
    await loadMetadataReview(songId);
}

function selectedAcceptedSuggestions(allEligible) {
    const fields = [...document.querySelectorAll("[data-accepted-field]:not(:disabled)")];
    return (allEligible ? fields : fields.filter((item) => item.checked)).map((item) => Number(item.dataset.acceptedField));
}

async function previewMetadataApplication(songId) {
    const ids = selectedAcceptedSuggestions(false);
    const target = document.getElementById("metadata-application-preview");
    if (!ids.length) { target.textContent = "Select one or more eligible accepted fields first."; return; }
    const response = await fetch(`/api/library/songs/${songId}/metadata/application-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ suggestion_ids: ids, initiated_by: "library-ui" }) });
    const preview = await response.json();
    if (!response.ok) { target.textContent = preview.error?.message || "Preview unavailable."; return; }
    const stale = preview.operations.some((item) => item.status === "stale");
    document.getElementById("metadata-force-control").hidden = !stale;
    preview.operations.filter((item) => ["invalid", "unsupported"].includes(item.status)).forEach((item) => {
        const input = document.querySelector(`[data-accepted-field="${item.suggestion_id}"]`);
        if (input) { input.checked = false; input.disabled = true; }
    });
    target.innerHTML = preview.operations.map((item) => `<article class="metadata-suggestion-card"><strong>${escapeHtml(item.field_name.replaceAll("_", " "))}</strong><p>${escapeHtml(metadataValue(item.current_value))} → ${escapeHtml(metadataValue(item.proposed_value))}</p><small>${escapeHtml(item.status)}${item.validation_error ? ` · ${escapeHtml(item.validation_error)}` : ""}</small>${item.status === "stale" ? `<small>Expected ${escapeHtml(metadataValue(item.expected_current_value))}; current canonical value differs.</small>` : ""}</article>`).join("");
}

async function submitMetadataApplication(songId, allEligible) {
    const ids = selectedAcceptedSuggestions(allEligible);
    const status = document.getElementById("metadata-review-status");
    if (!ids.length) { status.textContent = "No eligible accepted fields are selected."; return; }
    const force = document.getElementById("metadata-force").checked;
    const response = await fetch(`/api/library/songs/${songId}/metadata/apply-selected`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ suggestion_ids: ids, force, force_confirmation: force, initiated_by: "library-ui" }) });
    const result = await response.json();
    if (!response.ok) { status.textContent = result.error?.message || "Metadata application could not be queued."; return; }
    status.textContent = `Application queued (job ${result.job_id}).`;
    await pollMetadataApplication(result.job_id, songId);
}

async function pollMetadataApplication(jobId, songId) {
    const status = document.getElementById("metadata-review-status");
    let task = await fetchJson(`/api/tasks/jobs/${jobId}`);
    while (["queued", "running", "cancelling"].includes(task.status)) {
        status.textContent = `${task.status.replaceAll("_", " ")} · ${task.processed_items}/${task.total_items}.`;
        await new Promise((resolve) => setTimeout(resolve, 750));
        task = await fetchJson(`/api/tasks/jobs/${jobId}`);
    }
    status.textContent = task.status === "completed" ? "Library metadata updated. Audio-file tags were not modified." : `Metadata application ${task.status.replaceAll("_", " ")}; see task ${jobId} for details.`;
    await loadMetadataReview(songId);
}

async function discoverMetadataMatch(songId) {
    const status = document.getElementById("metadata-review-status");
    const target = document.getElementById("metadata-matches");
    status.textContent = "Discovering bounded provider candidates…";
    target.innerHTML = '<p class="library-search-status">Contacting metadata provider…</p>';
    try {
        const response = await fetch(`/api/metadata/discoveries/songs/${songId}`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: "musicbrainz" }),
        });
        const started = await response.json();
        if (!response.ok) throw new Error(started.error?.message || "Discovery failed");
        const job = started.job;
        const discoveryId = started.discovery.id;
        target.innerHTML = `<p class="library-search-status">Discovery job ${job.id} queued.</p><button class="btn-secondary" type="button" data-cancel-discovery="${job.id}">Cancel discovery</button>`;
        target.querySelector("[data-cancel-discovery]").onclick = async () => fetch(`/api/tasks/jobs/${job.id}/cancel`, {method:"POST"});
        let state = job;
        while (["queued", "running", "cancelling"].includes(state.status)) {
            await new Promise((resolve) => setTimeout(resolve, 750));
            state = await fetchJson(`/api/tasks/jobs/${job.id}`);
            status.textContent = `${state.status.replaceAll("_", " ")} · ${state.progress_percentage}% · ${state.processed_items}/${state.total_items}`;
        }
        if (["cancelled", "interrupted", "failed"].includes(state.status)) {
            target.innerHTML = `<p class="library-search-status">Discovery ${escapeHtml(state.status)}. Existing metadata was not changed.</p><button class="btn-secondary" type="button" data-retry-discovery>Retry discovery</button>`;
            target.querySelector("[data-retry-discovery]").onclick = () => discoverMetadataMatch(songId);
            return;
        }
        const discovery = await fetchJson(`/api/metadata/discoveries/${discoveryId}`);
        renderMetadataMatches(discovery, target);
        status.textContent = discovery.status === "completed_with_errors" ? "Partial results: one or more provider searches failed safely." : "Discovery complete. Selection does not accept metadata.";
    } catch (error) {
        target.innerHTML = '<p class="library-search-status">Provider discovery is unavailable. Existing metadata was not changed.</p>';
        status.textContent = error.message;
    }
}

function renderMetadataMatches(discovery, target) {
        target.innerHTML = `${discovery.stale ? '<p class="library-search-status">These results are stale because canonical metadata changed after discovery.</p>' : ""}${discovery.results.map((result) => {
            const candidate = result.candidate_summary;
            const label = result.confidence_level === "medium" ? "possible match" : result.confidence_level === "low" ? "weak match" : `${result.confidence_level} confidence`;
            return `<article class="metadata-suggestion-card">
                <header><strong>${escapeHtml(candidate.title || "Untitled candidate")}</strong><span>${result.score.toFixed(2)} · ${escapeHtml(result.ambiguous ? "ambiguous" : label)}</span></header>
                <p>${escapeHtml(candidate.artist || "Unknown artist")} · ${escapeHtml(candidate.album || "Release unavailable")} · ${escapeHtml(candidate.release_date || "Date unavailable")}</p>
                <small><b>Positive evidence:</b> ${escapeHtml(result.positive_evidence.map((item) => item.message).join(" · ") || "None")}</small>
                <small><b>Conflicts:</b> ${escapeHtml(result.conflicting_evidence.map((item) => item.message).join(" · ") || "None")}</small>
                <small><b>Unavailable:</b> ${escapeHtml(result.unavailable_evidence.map((item) => item.message).join(" · ") || "None")}</small>
                <small><b>Found by:</b> ${escapeHtml(result.search_provenance.join(" · ") || "Unknown")}</small>
                <label><input type="checkbox" data-compare-result="${result.id}"> Compare</label>
                ${result.viable ? `<button class="btn-secondary" type="button" data-match-result="${result.id}" data-discovery="${discovery.id}" data-confirm="${result.ambiguous || result.confidence_level === "low"}">Select candidate</button>` : "<b>Rejected candidate</b>"}
            </article>`;
        }).join("") || '<p class="library-search-status">No provider candidates were found.</p>'}<button class="btn-secondary" type="button" data-compare-selected>Compare two selected candidates</button><div data-comparison-output></div>`;
        target.querySelectorAll("[data-match-result]").forEach((button) => button.addEventListener("click", () => selectMetadataMatch(button)));
        target.querySelector("[data-compare-selected]").onclick = async () => {
            const ids=[...target.querySelectorAll("[data-compare-result]:checked")].map((item)=>item.dataset.compareResult);
            if (ids.length !== 2) { target.querySelector("[data-comparison-output]").textContent="Select exactly two candidates to compare."; return; }
            const comparison=await fetchJson(`/api/metadata/discoveries/${discovery.id}/compare?left_result_id=${ids[0]}&right_result_id=${ids[1]}`);
            target.querySelector("[data-comparison-output]").innerHTML=`<p><strong>Score difference:</strong> ${comparison.score_difference}</p><small>${escapeHtml(comparison.left.positive_evidence.map((x)=>x.message).join(" · "))}</small><small>${escapeHtml(comparison.right.positive_evidence.map((x)=>x.message).join(" · "))}</small>`;
        };
}

async function selectMetadataMatch(button) {
    const needsConfirmation = button.dataset.confirm === "true";
    if (needsConfirmation && !window.confirm("This candidate is ambiguous or low confidence. Select it for suggestion generation anyway?")) return;
    const response = await fetch(`/api/metadata/discoveries/${button.dataset.discovery}/select`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
        result_id:Number(button.dataset.matchResult), confirm_ambiguous:needsConfirmation, confirm_low_confidence:needsConfirmation,
    })});
    if (!response.ok) { document.getElementById("metadata-review-status").textContent="Candidate selection could not be saved."; return; }
    const generateButton = button.cloneNode(true);
    generateButton.textContent = "Generate pending suggestions";
    button.replaceWith(generateButton);
    generateButton.addEventListener("click", async () => {
        generateButton.disabled = true;
        const generate = await fetch(`/api/metadata/discoveries/${generateButton.dataset.discovery}/suggestions`, {method:"POST"});
        document.getElementById("metadata-review-status").textContent = generate.ok ? "Pending suggestions generated; acceptance remains a separate decision." : "The selected candidate produced no new applicable suggestions.";
        await loadMetadataReview(Number(document.getElementById("metadata-review-dialog").dataset.songId));
    });
    document.getElementById("metadata-review-status").textContent = "Candidate selected. Generate suggestions only if you want field-level proposals.";
}

async function loadMetadataReview(songId) {
    const status = document.getElementById("metadata-review-status");
    status.textContent = "Loading metadata review…";
    try {
        const [review, history] = await Promise.all([
            fetchJson(`/api/library/songs/${songId}/metadata`),
            fetchJson(`/api/library/songs/${songId}/metadata/history`),
        ]);
        const song = libraryState.songs.find((item) => item.id === songId);
        document.getElementById("metadata-review-title").textContent = song?.title || song?.filename || `Song ${songId}`;
        document.getElementById("metadata-current").innerHTML = review.fields
            .filter((field) => field.current_value !== null && field.current_value !== "")
            .map((field) => `<div><dt>${escapeHtml(field.field_name.replaceAll("_", " "))}</dt><dd>${escapeHtml(metadataValue(field.current_value))}</dd></div>`).join("") || "<p>No canonical metadata is indexed.</p>";
        const pending = review.fields.flatMap((field) => field.suggestions).filter((item) => item.status === "pending");
        document.getElementById("metadata-suggestions").innerHTML = pending.map((item) => `
            <article class="metadata-suggestion-card">
                <header><strong>${escapeHtml(item.field_name.replaceAll("_", " "))}</strong><span>${escapeHtml(item.provider)} · ${escapeHtml(item.confidence_level)}${item.confidence === null ? "" : ` (${Math.round(item.confidence * 100)}%)`}</span></header>
                <p class="metadata-proposed">${escapeHtml(metadataValue(item.current_value))} <span aria-hidden="true">→</span> <strong>${escapeHtml(metadataValue(item.suggested_value))}</strong></p>
                <p>${escapeHtml(item.match_explanation || "No match explanation supplied.")}</p>
                <small><b>Positive evidence:</b> ${escapeHtml(evidenceText(item.positive_evidence))}</small>
                <small><b>Conflicting evidence:</b> ${escapeHtml(evidenceText(item.conflicting_evidence))}</small>
                <div><button class="btn-primary" data-metadata-action="accept" data-suggestion-id="${item.id}">Accept</button><button class="btn-secondary" data-metadata-action="reject" data-suggestion-id="${item.id}">Reject</button></div>
            </article>`).join("") || '<p class="library-search-status">No pending suggestions.</p>';
        const accepted = review.fields.flatMap((field) => field.suggestions).filter((item) => item.status === "accepted");
        const acceptedTarget = document.getElementById("metadata-accepted");
        acceptedTarget.innerHTML = accepted.map((item) => `
            <article class="metadata-suggestion-card">
                <header><strong>${escapeHtml(item.field_name.replaceAll("_", " "))}</strong><span>${escapeHtml(item.provider)} · ${escapeHtml(item.confidence_level)}${item.confidence === null ? "" : ` (${Math.round(item.confidence * 100)}%)`}</span></header>
                <p class="metadata-proposed">${escapeHtml(metadataValue(item.current_value))} <span aria-hidden="true">→</span> <strong>${escapeHtml(metadataValue(item.suggested_value))}</strong></p>
                <label><input type="checkbox" data-accepted-field="${item.id}"> Select this field for preview or application</label><small>Validation and stale state are verified by Preview before application.</small>
            </article>`).join("") || '<p class="library-search-status">No accepted suggestions are available.</p>';
        document.getElementById("metadata-history").innerHTML = history.items.map((item) => `
            <article><strong>${escapeHtml(item.field_name.replaceAll("_", " "))}</strong><span>${escapeHtml(metadataValue(item.previous_value))} → ${escapeHtml(metadataValue(item.new_value))}</span><small>${escapeHtml(item.change_source)} · ${new Date(item.changed_at).toLocaleString()}</small></article>`).join("") || '<p class="library-search-status">No applied-change history.</p>';
        document.querySelectorAll("[data-metadata-action]").forEach((button) => button.addEventListener("click", () => reviewMetadataSuggestion(button)));
        document.getElementById("metadata-preview-tags").onclick = () => previewFileTags(songId);
        document.getElementById("metadata-write-tags").onclick = () => writeFileTags(songId);
        await previewFileTags(songId);
        status.textContent = "Accepting records a decision only; it does not change tags or canonical metadata.";
    } catch (error) {
        status.textContent = "Harmony could not load this metadata review.";
    }
}

async function previewFileTags(songId) {
    const target = document.getElementById("metadata-tag-preview");
    const button = document.getElementById("metadata-write-tags");
    try {
        const preview = await fetchJson(`/api/library/songs/${songId}/metadata/tag-preview`);
        button.disabled = !preview.available;
        target.innerHTML = preview.available
            ? preview.fields.map((field) => `<article class="metadata-suggestion-card"><strong>${escapeHtml(field.field.replaceAll("_", " "))}</strong><p>${escapeHtml(metadataValue(field.current))} → ${escapeHtml(metadataValue(field.canonical))}</p><small>${field.will_change ? "Will change" : "Already matches"}</small></article>`).join("") + `<article class="metadata-suggestion-card"><strong>Cached canonical artwork</strong><p>${escapeHtml(preview.artwork.status)}</p><label><input id="metadata-embed-artwork" type="checkbox" ${preview.artwork.canonical_available ? "checked" : "disabled"}> Embed canonical artwork in this audio file</label><small>Harmony's private cached artwork is distinct from artwork embedded in the file.</small></article>`
            : "<p class=\"library-search-status\">Tags cannot be written: the file is missing, unsafe, unsupported, or canonical metadata is unavailable.</p>";
    } catch (_) { button.disabled = true; target.textContent = "Tag preview is unavailable."; }
}

async function writeFileTags(songId) {
    const embedArtwork = document.getElementById("metadata-embed-artwork")?.checked ?? false;
    if (!window.confirm(`This will modify the audio file's embedded tags${embedArtwork ? " and artwork" : ""}. Continue?`)) return;
    const status = document.getElementById("metadata-review-status");
    const button = document.getElementById("metadata-write-tags"); button.disabled = true;
    try {
        const response = await fetch(`/api/library/songs/${songId}/metadata/write-tags`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ embed_artwork: embedArtwork }) });
        const result = await response.json();
        status.textContent = result.status === "succeeded" ? (result.artwork === "embedded" ? "Tags and artwork written." : "Canonical tags were written to the audio file.") : "Tags were not written; the file was left unchanged.";
        await previewFileTags(songId);
    } catch (_) { status.textContent = "Harmony could not write tags to this audio file."; button.disabled = false; }
}

async function reviewMetadataSuggestion(button) {
    button.disabled = true;
    const response = await fetch(`/api/metadata/suggestions/${button.dataset.suggestionId}/${button.dataset.metadataAction}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reviewed_by: "library-ui" }),
    });
    if (!response.ok) {
        document.getElementById("metadata-review-status").textContent = "The review decision could not be saved.";
        button.disabled = false;
        return;
    }
    await loadMetadataReview(Number(document.getElementById("metadata-review-dialog").dataset.songId));
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

function renderCollections() {
    const grid = document.getElementById("collections-grid");
    const collectionIcons = {
        recent: icons.recent,
        download: icons.download,
        quality: icons.quality,
        artwork: icons.artwork,
        metadata: icons.metadata,
        modified: icons.modified,
        album: icons.album,
        favorite: icons.favorite,
    };

    grid.innerHTML = libraryState.filteredCollections.length
        ? libraryState.filteredCollections.map((collection) => `
            <button class="library-collection-card tone-${escapeAttribute(collection.tone)}" type="button" data-collection="${escapeAttribute(collection.id)}" data-name="${escapeAttribute(collection.name)}" ${collection.placeholder ? "disabled" : ""}>
                <span class="library-collection-icon">${collectionIcons[collection.icon] || icons.music}</span>
                <span class="library-collection-copy">
                    <small>Smart collection</small>
                    <strong>${escapeHtml(collection.name)}</strong>
                    <span>${escapeHtml(collection.description)}</span>
                </span>
                <span class="library-collection-count">
                    <b>${Number(collection.song_count || 0).toLocaleString()}</b>
                    <small>${collection.placeholder ? "Coming soon" : pluralizeLabel(collection.song_count, "song")}</small>
                </span>
            </button>
        `).join("")
        : emptyGrid("No collections match your search.");

    grid.querySelectorAll("[data-collection]").forEach((card) => {
        card.addEventListener("click", () => applyCollection(card.dataset.collection, card.dataset.name));
    });
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
    document.getElementById("library-sort").disabled = view === "collections";
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

async function applyCollection(collectionId, name) {
    libraryState.collectionId = collectionId;
    libraryState.query = "";
    document.getElementById("library-search").value = "";
    const chip = document.getElementById("clear-collection");
    document.getElementById("collection-filter-name").textContent = name;
    chip.hidden = false;
    libraryState.pages.songs = 1;
    switchView("songs");
    await loadLibraryData({ preserveState: true });
}

async function clearCollection() {
    libraryState.collectionId = null;
    document.getElementById("clear-collection").hidden = true;
    libraryState.pages.songs = 1;
    await loadLibraryData({ preserveState: true });
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
    write_tags: {
        title: "Write canonical tags?",
        message: "Harmony will modify each selected audio file's embedded tags. This is required before Navidrome can read the canonical values.",
        confirm: "Write tags",
    },
    refresh_artwork: {
        title: "Refresh artwork cache?",
        message: "Harmony will re-read embedded and folder artwork and repair local cache associations.",
        confirm: "Refresh artwork",
    },
    fetch_artwork: {
        title: "Fetch album art from Cover Art Archive?",
        message: "Harmony will use each song's canonical MusicBrainz release ID to download and cache the release's front artwork. Release-group IDs cannot be used for this lookup; songs without a release ID will be skipped with an explanation.",
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
    if (operation === "write_tags") {
        const response = await fetch("/api/library/metadata/write-tags", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ song_ids: [...libraryState.selectedSongs], embed_artwork: true }) });
        if (!response.ok) throw new Error("Unable to write canonical tags.");
        const result = await response.json();
        document.getElementById("library-bulk-progress").hidden = false;
        document.getElementById("library-bulk-progress-title").textContent = "Canonical tag writing finished";
        document.getElementById("library-bulk-progress-detail").textContent = `Tag writing finished: ${result.totals.succeeded} succeeded, ${result.totals.skipped} skipped, ${result.totals.unsupported} unsupported, ${result.totals.missing} missing, ${result.totals.failed} failed. Artwork: ${result.totals.artwork_embedded} embedded, ${result.totals.artwork_unchanged} unchanged, ${result.totals.artwork_unavailable} unavailable, ${result.totals.artwork_unsupported} unsupported, ${result.totals.artwork_failed} failed.`;
        await loadLibrary();
        return;
    }
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
            await loadAnalytics();
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
document.getElementById("metadata-review-close").addEventListener("click", () => document.getElementById("metadata-review-dialog").close());

document.getElementById("library-clear-selection").addEventListener("click", clearBulkSelection);
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
        if (libraryState.collectionId !== null) {
            libraryState.collectionId = null;
            document.getElementById("clear-collection").hidden = true;
            await loadLibraryData({ preserveState: true });
        } else {
            performSearch();
        }
    }, 180);
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

document.getElementById("clear-collection").addEventListener("click", clearCollection);

document.getElementById("btn-rescan").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span><span>Rescanning…</span>`;
    try {
        const response = await fetch("/api/library/rescan", { method: "POST" });
        if (!response.ok) throw new Error("Rescan failed");
        await loadLibraryData({ preserveState: true });
        await loadAnalytics();
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
            setTimeout(loadAnalytics, 550);
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    const requestedView = params.get("view");
    const requestedAlbumKey = params.get("album_key");
    const requestedSongId = Number(params.get("song"));
    const requestedAvailability = params.get("availability");
    if (requestedAlbumKey) {
        libraryState.requestedAlbumKey = requestedAlbumKey;
        Object.assign(libraryState.filters, { artist: "", album: "", genre: "", codec: "", bitrate: "", downloaded_today: false, recently_added: false, missing_artwork: false, missing_metadata: false });
    }
    if (["songs", "albums", "artists", "collections"].includes(requestedView)) libraryState.view = requestedView;
    if (Number.isInteger(requestedSongId) && requestedSongId > 0) {
        libraryState.requestedSongId = requestedSongId;
        libraryState.view = "songs";
        if (params.get("metadata") === "review") libraryState.requestedMetadataReviewSongId = requestedSongId;
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
    loadAnalytics();
    connectLibraryEvents();
});
