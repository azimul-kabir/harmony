const libraryState = {
    songs: [],
    albums: [],
    artists: [],
    collections: [],
    filteredSongs: [],
    filteredAlbums: [],
    filteredArtists: [],
    filteredCollections: [],
    view: "songs",
    sort: "artist",
    query: "",
    collectionFilter: null,
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

async function loadLibraryData({ preserveState = false } = {}) {
    const loading = document.getElementById("library-loading");
    const errorBox = document.getElementById("library-error");
    if (!preserveState) loading.hidden = false;
    errorBox.hidden = true;

    try {
        const [songs, albums, artists, collections] = await Promise.all([
            fetchJson(`/api/library/songs?sort_by=${encodeURIComponent(libraryState.sort)}`),
            fetchJson("/api/library/albums"),
            fetchJson("/api/library/artists"),
            fetchJson("/api/library/collections"),
        ]);

        Object.assign(libraryState, { songs, albums, artists, collections });
        applyFilters();
        updateCounts();
        renderActiveView();
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
        applyFilters();
        renderActiveView();
    }, 180);
});

document.getElementById("library-sort").addEventListener("change", (event) => {
    libraryState.sort = event.target.value;
    libraryState.pages.songs = 1;
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
    loadLibraryData();
    connectLibraryEvents();
});
