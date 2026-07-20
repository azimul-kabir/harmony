const LIBRARY_PREFERENCES_KEY = "harmony.library.preferences.v1";
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
    collections: [],
    filterOptions: null,
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
    collectionFilter: null,
    searchTotal: 0,
    searchRequest: 0,
    pages: { songs: 1, albums: 1, artists: 1 },
    pageSize: 24,
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
};

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
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
    return params.toString();
}

function projectSongs(songs) {
    const albumMap = new Map();
    const artistMap = new Map();
    songs.forEach((song) => {
        const album = song.album || "Unknown Album";
        const artist = song.album_artist || song.artist || "Unknown Artist";
        const albumKey = `${artist}\u0000${album}`;
        const albumItem = albumMap.get(albumKey) || {
            album,
            artist,
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
        const [songs, collections, filterOptions] = await Promise.all([
            fetchJson(`/api/library/songs?${libraryRequestParams()}`),
            fetchJson("/api/library/collections"),
            libraryState.filterOptions || fetchJson("/api/library/filter-options"),
        ]);

        const { albums, artists } = projectSongs(songs);
        Object.assign(libraryState, { songs, albums, artists, collections, filterOptions });
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
    let songs = libraryState.songs.filter(songMatchesCollection);

    if (query) {
        songs = songs.filter((song) => [song.title, song.artist, song.album, song.filename]
            .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
    }

    libraryState.filteredSongs = songs;
    libraryState.filteredAlbums = libraryState.albums.filter((album) => !query ||
        [album.album, album.artist].some((value) => String(value || "").toLocaleLowerCase().includes(query)));
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
    switch (libraryState.collectionFilter) {
        case "recently_added": return Boolean(song.recently_added);
        case "high_bitrate": return Number(song.bitrate || 0) >= 320000;
        case "missing_artwork": return song.artwork_status === "missing";
        case "missing_metadata": return !song.title || !song.artist || !song.album;
        default: return true;
    }
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
            <tr>
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
            </tr>
        `).join("");
    }

    renderPagination("pagination-songs", page, "songs", renderSongs);
}

function renderAlbums() {
    const page = pageItems(libraryState.filteredAlbums, "albums");
    const grid = document.getElementById("albums-grid");

    grid.innerHTML = page.items.length ? page.items.map((album) => `
        <button class="library-album-card" type="button" data-album="${escapeAttribute(album.album)}">
            ${artwork(album.cover_url, "library-album-artwork")}
            <span class="library-album-copy">
                <strong title="${escapeAttribute(album.album)}">${escapeHtml(album.album || "Unknown album")}</strong>
                <span>${escapeHtml(album.artist || "Unknown artist")}</span>
                <small>${pluralize(album.track_count, "song")}</small>
            </span>
        </button>
    `).join("") : emptyGrid("No albums match your search.");

    grid.querySelectorAll("[data-album]").forEach((card) => {
        card.addEventListener("click", () => showSongsFor("album", card.dataset.album));
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
        "recently-added": icons.recent,
        "high-bitrate": icons.quality,
        "missing-artwork": icons.artwork,
        "missing-metadata": icons.metadata,
    };

    grid.innerHTML = libraryState.filteredCollections.length
        ? libraryState.filteredCollections.map((collection) => `
            <button class="library-collection-card tone-${escapeAttribute(collection.tone)}" type="button" data-collection="${escapeAttribute(collection.filter)}" data-name="${escapeAttribute(collection.name)}">
                <span class="library-collection-icon">${collectionIcons[collection.id] || icons.music}</span>
                <span class="library-collection-copy">
                    <small>Smart collection</small>
                    <strong>${escapeHtml(collection.name)}</strong>
                    <span>${escapeHtml(collection.description)}</span>
                </span>
                <span class="library-collection-count">
                    <b>${Number(collection.song_count || 0).toLocaleString()}</b>
                    <small>${pluralizeLabel(collection.song_count, "song")}</small>
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

function showSongsFor(field, value) {
    libraryState.collectionFilter = null;
    libraryState.query = value || "";
    document.getElementById("library-search").value = libraryState.query;
    applyFilters();
    if (field === "album") {
        libraryState.filteredSongs = libraryState.songs.filter((song) => (song.album || "") === value);
    } else {
        libraryState.filteredSongs = libraryState.songs.filter((song) => (song.artist || "") === value);
    }
    libraryState.pages.songs = 1;
    switchView("songs");
}

function applyCollection(filter, name) {
    libraryState.collectionFilter = filter;
    libraryState.query = "";
    document.getElementById("library-search").value = "";
    const chip = document.getElementById("clear-collection");
    document.getElementById("collection-filter-name").textContent = name;
    chip.hidden = false;
    libraryState.pages.songs = 1;
    applyFilters();
    switchView("songs");
}

function clearCollection() {
    libraryState.collectionFilter = null;
    document.getElementById("clear-collection").hidden = true;
    libraryState.pages.songs = 1;
    applyFilters();
    renderActiveView();
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
    return `<tr><td colspan="5"><div class="library-empty">${icons.music}<strong>${escapeHtml(message)}</strong></div></td></tr>`;
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

document.querySelectorAll(".library-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
});

document.getElementById("library-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        libraryState.query = event.target.value;
        Object.keys(libraryState.pages).forEach((key) => { libraryState.pages[key] = 1; });
        performSearch();
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
    ["library.track.added", "library.track.updated", "library.track.missing", "library.track.renamed"].forEach((type) => {
        events.addEventListener(type, () => {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(() => loadLibraryData({ preserveState: true }), 500);
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("library-sort").value = libraryState.sort;
    updateFilterControls();
    loadLibraryData();
    connectLibraryEvents();
});
