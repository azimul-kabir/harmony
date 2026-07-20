let allSongs = [];
let filteredSongs = [];
let allAlbums = [];
let filteredAlbums = [];
let allArtists = [];
let filteredArtists = [];

let currentSongPage = 1;
let currentAlbumPage = 1;
let currentArtistPage = 1;
const itemsPerPage = 50;
let searchTimeout = null;
let currentView = 'songs';
let currentSort = 'artist';

async function loadLibraryData() {
    try {
        const resSongs = await fetch(`/api/library/songs?sort_by=${currentSort}`);
        if (!resSongs.ok) throw new Error("Failed to fetch songs");
        allSongs = await resSongs.json();
        filteredSongs = allSongs;

        const [resAlbums, resArtists] = await Promise.all([
            fetch("/api/library/albums"),
            fetch("/api/library/artists")
        ]);
        
        if (resAlbums.ok) {
            allAlbums = await resAlbums.json();
            filteredAlbums = allAlbums;
        }
        if (resArtists.ok) {
            allArtists = await resArtists.json();
            filteredArtists = allArtists;
        }

        renderActiveView();
    } catch (e) {
        console.error("Library load error:", e);
        document.getElementById("library-body").innerHTML = `
            <tr>
                <td colspan="4" class="text-center empty-state" style="padding: 40px; color: var(--danger);">
                    Failed to load library data.
                </td>
            </tr>
        `;
    }
}

function renderActiveView() {
    // Show/hide respective pagination blocks if needed
    if (currentView === 'songs') {
        renderSongsPage();
        setPaginationVisibility(true, false, false);
    } else if (currentView === 'albums') {
        renderAlbumsPage();
        setPaginationVisibility(false, true, false);
    } else if (currentView === 'artists') {
        renderArtistsPage();
        setPaginationVisibility(false, false, true);
    }
}

function setPaginationVisibility(songsVis, albumsVis, artistsVis) {
    document.getElementById("pagination-songs").style.display = songsVis ? "flex" : "none";
    
    let albumPag = document.getElementById("pagination-albums");
    if (!albumPag && albumsVis) {
        createPaginationContainer("pagination-albums", changeAlbumPage);
    }
    if (albumPag) albumPag.style.display = albumsVis ? "flex" : "none";

    let artistPag = document.getElementById("pagination-artists");
    if (!artistPag && artistsVis) {
        createPaginationContainer("pagination-artists", changeArtistPage);
    }
    if (artistPag) artistPag.style.display = artistsVis ? "flex" : "none";
}

function createPaginationContainer(id, callback) {
    const parent = document.querySelector("#view-" + id.replace("pagination-", ""));
    const div = document.createElement("div");
    div.id = id;
    div.className = "pagination-controls";
    div.style = "border-radius: 0 0 16px 16px; background: var(--bg-surface-alt); margin-top: 16px; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center;";
    div.innerHTML = `
        <button class="btn-secondary prev-btn" disabled>Previous</button>
        <span class="page-info" style="font-weight: 600; color: var(--text-muted);">Page 1</span>
        <button class="btn-secondary next-btn" disabled>Next</button>
    `;
    parent.appendChild(div);

    div.querySelector(".prev-btn").onclick = () => callback(-1);
    div.querySelector(".next-btn").onclick = () => callback(1);
}

function renderSongsPage() {
    const tbody = document.getElementById("library-body");
    const startIndex = (currentSongPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredSongs.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-center empty-state" style="padding: 40px;">
                    No tracks found matching your criteria.
                </td>
            </tr>
        `;
    } else {
        tbody.innerHTML = paginatedItems.map(s => {
            const coverImg = s.cover_url
                ? `<img src="${s.cover_url}" alt="Cover" style="width: 40px; height: 40px; border-radius: 6px; object-fit: cover; flex-shrink: 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">`
                : `<div style="width: 40px; height: 40px; border-radius: 6px; background: var(--bg-surface-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--text-muted); border: 1px solid var(--border-color);"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

            return `
            <tr>
                <td style="padding-left: 24px; vertical-align: middle;">
                    <input type="checkbox" class="song-check" data-id="${s.id}" style="cursor: pointer;">
                </td>
                <td style="font-weight: 600; color: var(--text-main);">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        ${coverImg}
                        <div style="display: flex; flex-direction: column; justify-content: center;">
                            <span style="font-size: 1.05rem;">${s.title || 'Unknown Title'}</span>
                            ${!s.title && s.filename ? `<span style="font-size: 0.8rem; font-weight: normal; color: var(--danger); margin-top: 2px; word-break: break-all;">${s.filename}</span>` : ''}
                        </div>
                    </div>
                </td>
                <td style="color: var(--text-muted); vertical-align: middle;">${s.artist || 'Unknown Artist'}</td>
                <td style="color: var(--text-muted); vertical-align: middle;">${s.album || 'Unknown Album'}</td>
            </tr>
            `;
        }).join("");
    }

    updateSongsPaginationUI();
    const selectAll = document.getElementById("select-all");
    if(selectAll) selectAll.checked = false;
    document.getElementById("delete-selected").disabled = true;
}

function renderAlbumsPage() {
    const grid = document.getElementById("albums-grid");
    const startIndex = (currentAlbumPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredAlbums.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        grid.innerHTML = `<p class="empty-state" style="grid-column: 1/-1; padding: 40px;">No albums found matching your criteria.</p>`;
        updateGenericPaginationUI("pagination-albums", currentAlbumPage, filteredAlbums.length);
        return;
    }

    grid.innerHTML = paginatedItems.map(album => {
        const coverImg = album.cover_url
            ? `<img src="${album.cover_url}" alt="Cover" style="width: 100%; height: 160px; border-radius: 8px; object-fit: cover; margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">`
            : `<div style="width: 100%; height: 160px; border-radius: 8px; background: var(--bg-surface-alt); display: flex; align-items: center; justify-content: center; margin-bottom: 12px; color: var(--text-muted); border: 1px solid var(--border-color);"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

        return `
            <div class="source-card" style="cursor: pointer;" onclick="filterByAlbum('${encodeURIComponent(album.album)}')">
                ${coverImg}
                <h3 style="margin: 0 0 4px 0; font-size: 1.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${album.album}">${album.album}</h3>
                <div style="color: var(--text-muted); font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 12px;">${album.artist}</div>
                <div class="source-meta" style="display: flex; justify-content: space-between; font-size: 0.85rem; padding: 8px 12px;">
                    <span>${album.track_count} Tracks</span>
                    <span>${album.total_duration} mins</span>
                </div>
            </div>
        `;
    }).join("");

    updateGenericPaginationUI("pagination-albums", currentAlbumPage, filteredAlbums.length);
}

function renderArtistsPage() {
    const grid = document.getElementById("artists-grid");
    const startIndex = (currentArtistPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredArtists.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        grid.innerHTML = `<p class="empty-state" style="grid-column: 1/-1; padding: 40px;">No artists found matching your criteria.</p>`;
        updateGenericPaginationUI("pagination-artists", currentArtistPage, filteredArtists.length);
        return;
    }

    grid.innerHTML = paginatedItems.map(artist => {
        const coverImg = artist.cover_url
            ? `<img src="${artist.cover_url}" alt="Cover" style="width: 60px; height: 60px; border-radius: 50%; object-fit: cover; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">`
            : `<div style="width: 60px; height: 60px; border-radius: 50%; background: var(--bg-surface-alt); display: flex; align-items: center; justify-content: center; color: var(--text-muted); border: 1px solid var(--border-color);"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg></div>`;

        return `
            <div class="source-card" style="flex-direction: row; align-items: center; gap: 16px; cursor: pointer;" onclick="filterByArtist('${encodeURIComponent(artist.artist)}')">
                ${coverImg}
                <div style="min-width: 0; flex: 1;">
                    <h3 style="margin: 0 0 4px 0; font-size: 1.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${artist.artist}">${artist.artist}</h3>
                    <div style="color: var(--text-muted); font-size: 0.85rem;">${artist.song_count} Songs • ${artist.album_count} Albums</div>
                </div>
            </div>
        `;
    }).join("");

    updateGenericPaginationUI("pagination-artists", currentArtistPage, filteredArtists.length);
}

function updateSongsPaginationUI() {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage) || 1;
    document.getElementById("page-info").textContent = `Page ${currentSongPage} of ${totalPages} (${filteredSongs.length} total tracks)`;
    document.getElementById("btn-prev").disabled = currentSongPage === 1;
    document.getElementById("btn-next").disabled = currentSongPage === totalPages;
}

function updateGenericPaginationUI(containerId, page, totalLength) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const totalPages = Math.ceil(totalLength / itemsPerPage) || 1;
    container.querySelector(".page-info").textContent = `Page ${page} of ${totalPages} (${totalLength} items)`;
    container.querySelector(".prev-btn").disabled = page === 1;
    container.querySelector(".next-btn").disabled = page === totalPages;
}

function changeAlbumPage(direction) {
    const totalPages = Math.ceil(filteredAlbums.length / itemsPerPage) || 1;
    currentAlbumPage += direction;
    if (currentAlbumPage < 1) currentAlbumPage = 1;
    if (currentAlbumPage > totalPages) currentAlbumPage = totalPages;
    renderAlbumsPage();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function changeArtistPage(direction) {
    const totalPages = Math.ceil(filteredArtists.length / itemsPerPage) || 1;
    currentArtistPage += direction;
    if (currentArtistPage < 1) currentArtistPage = 1;
    if (currentArtistPage > totalPages) currentArtistPage = totalPages;
    renderArtistsPage();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function filterByAlbum(albumName) {
    currentView = 'songs';
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-view="songs"]').classList.add('active');
    document.getElementById('view-songs').style.display = 'block';
    document.getElementById('view-albums').style.display = 'none';
    document.getElementById('view-artists').style.display = 'none';

    const decoded = decodeURIComponent(albumName);
    document.getElementById("library-search").value = decoded;
    filteredSongs = allSongs.filter(s => (s.album || "").toLowerCase() === decoded.toLowerCase());
    currentSongPage = 1;
    renderActiveView();
}

function filterByArtist(artistName) {
    currentView = 'songs';
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-view="songs"]').classList.add('active');
    document.getElementById('view-songs').style.display = 'block';
    document.getElementById('view-albums').style.display = 'none';
    document.getElementById('view-artists').style.display = 'none';

    const decoded = decodeURIComponent(artistName);
    document.getElementById("library-search").value = decoded;
    filteredSongs = allSongs.filter(s => (s.artist || "").toLowerCase() === decoded.toLowerCase());
    currentSongPage = 1;
    renderActiveView();
}

// View Tab Switching Logic
document.querySelectorAll("#library-view-tabs .filter-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
        document.querySelectorAll("#library-view-tabs .filter-tab").forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        currentView = e.target.dataset.view;

        document.getElementById('view-songs').style.display = currentView === 'songs' ? 'block' : 'none';
        document.getElementById('view-albums').style.display = currentView === 'albums' ? 'block' : 'none';
        document.getElementById('view-artists').style.display = currentView === 'artists' ? 'block' : 'none';

        renderActiveView();
    });
});

// Sorting Dropdown Change
document.getElementById("library-sort")?.addEventListener("change", async (e) => {
    currentSort = e.target.value;
    await loadLibraryData();
});

// Pagination Event Listeners for Songs
document.getElementById("btn-prev")?.addEventListener("click", () => {
    if (currentSongPage > 1) {
        currentSongPage--;
        renderSongsPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

document.getElementById("btn-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage);
    if (currentSongPage < totalPages) {
        currentSongPage++;
        renderSongsPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

// Global Unified Search Logic across Songs, Albums, and Artists
document.getElementById("library-search")?.addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        const q = e.target.value.toLowerCase().trim();
        if (!q) {
            filteredSongs = allSongs;
            filteredAlbums = allAlbums;
            filteredArtists = allArtists;
        } else {
            filteredSongs = allSongs.filter(s => 
                (s.title || "").toLowerCase().includes(q) || 
                (s.artist || "").toLowerCase().includes(q) ||
                (s.album || "").toLowerCase().includes(q) ||
                (s.genre || "").toLowerCase().includes(q) ||
                (s.filename || "").toLowerCase().includes(q)
            );
            filteredAlbums = allAlbums.filter(a => 
                (a.album || "").toLowerCase().includes(q) ||
                (a.artist || "").toLowerCase().includes(q)
            );
            filteredArtists = allArtists.filter(art => 
                (art.artist || "").toLowerCase().includes(q)
            );
        }
        currentSongPage = 1;
        currentAlbumPage = 1;
        currentArtistPage = 1;
        renderActiveView();
    }, 250);
});

// Batch Delete logic
document.getElementById("delete-selected")?.addEventListener("click", async (e) => {
    const selected = Array.from(document.querySelectorAll(".song-check:checked"));
    if (selected.length === 0) return;

    if (!confirm(`Are you sure you want to permanently delete ${selected.length} track(s) from your hard drive? This cannot be undone.`)) return;

    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width: 12px; height: 12px; border-top-color: white;"></span> Deleting...';
    try {
        for (const el of selected) {
            await fetch(`/api/library/song/${el.dataset.id}`, { method: "DELETE" });
        }
    } finally {
        btn.textContent = "Delete Selected";
        btn.disabled = true;
        await loadLibraryData();
    }
});

// Rescan Library Logic
document.getElementById("btn-rescan")?.addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="border-top-color: var(--primary);"></span> Scanning Storage...';

    try {
        await fetch("/api/library/rescan", { method: "POST" });
    } catch (err) {
        console.error("Rescan failed:", err);
    } finally {
        setTimeout(() => {
            btn.innerHTML = '  Rescan Library';
            btn.disabled = false;
            loadLibraryData();
        }, 1000);
    }
});

// Enable/Disable delete button & Select All checkboxes
document.addEventListener("change", (e) => {
    if (e.target.id === "select-all") {
        const isChecked = e.target.checked;
        document.querySelectorAll(".song-check").forEach(cb => cb.checked = isChecked);
    }

    if (e.target.classList.contains("song-check") || e.target.id === "select-all") {
        const count = document.querySelectorAll(".song-check:checked").length;
        document.getElementById("delete-selected").disabled = count === 0;
    }
});

// Initialize on load
document.addEventListener("DOMContentLoaded", loadLibraryData);
