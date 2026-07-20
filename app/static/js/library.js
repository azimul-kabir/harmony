let allSongs = [];
let filteredSongs = [];
let allAlbums = [];
let filteredAlbums = [];
let allArtists = [];
let filteredArtists = [];

let currentSongPage = 1;
let currentAlbumPage = 1;
let currentArtistPage = 1;
const itemsPerPage = 30; // Optimized for mobile scrolling performance
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
    document.getElementById('view-songs').style.display = currentView === 'songs' ? 'block' : 'none';
    document.getElementById('view-albums').style.display = currentView === 'albums' ? 'block' : 'none';
    document.getElementById('view-artists').style.display = currentView === 'artists' ? 'block' : 'none';

    if (currentView === 'songs') {
        renderSongsPage();
    } else if (currentView === 'albums') {
        renderAlbumsPage();
    } else if (currentView === 'artists') {
        renderArtistsPage();
    }
}

function renderSongsPage() {
    const tbody = document.getElementById("library-body");
    const startIndex = (currentSongPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredSongs.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center empty-state" style="padding: 40px;">No tracks found.</td></tr>`;
    } else {
        tbody.innerHTML = paginatedItems.map(s => {
            const coverImg = s.cover_url
                ? `<img src="${s.cover_url}" alt="Cover" style="width: 40px; height: 40px; border-radius: 6px; object-fit: cover; flex-shrink: 0;">`
                : `<div style="width: 40px; height: 40px; border-radius: 6px; background: var(--bg-surface-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--text-muted);"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

            return `
            <tr>
                <td style="padding-left: 24px; vertical-align: middle;">
                    <input type="checkbox" class="song-check" data-id="${s.id}" style="cursor: pointer;">
                </td>
                <td style="font-weight: 600; color: var(--text-main);">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        ${coverImg}
                        <span>${s.title || 'Unknown Title'}</span>
                    </div>
                </td>
                <td style="color: var(--text-muted); vertical-align: middle;">${s.artist || 'Unknown Artist'}</td>
                <td style="color: var(--text-muted); vertical-align: middle;">${s.album || 'Unknown Album'}</td>
            </tr>
            `;
        }).join("");
    }
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage) || 1;
    document.getElementById("page-info").textContent = `Page ${currentSongPage} of ${totalPages} (${filteredSongs.length} tracks)`;
    document.getElementById("btn-prev").disabled = currentSongPage === 1;
    document.getElementById("btn-next").disabled = currentSongPage === totalPages;
}

function renderAlbumsPage() {
    const grid = document.getElementById("albums-grid");
    const startIndex = (currentAlbumPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredAlbums.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        grid.innerHTML = `<p class="empty-state" style="grid-column: 1/-1; padding: 40px;">No albums found.</p>`;
    } else {
        grid.innerHTML = paginatedItems.map(album => {
            const coverImg = album.cover_url
                ? `<img src="${album.cover_url}" alt="Cover" style="width: 100%; height: 150px; border-radius: 8px; object-fit: cover; margin-bottom: 12px;">`
                : `<div style="width: 100%; height: 150px; border-radius: 8px; background: var(--bg-surface-alt); display: flex; align-items: center; justify-content: center; margin-bottom: 12px; color: var(--text-muted);"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

            return `
                <div class="source-card" style="cursor: pointer;" onclick="filterByAlbum('${encodeURIComponent(album.album)}')">
                    ${coverImg}
                    <h3 style="margin: 0 0 4px 0; font-size: 1.05rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${album.album}</h3>
                    <div style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 8px;">${album.artist}</div>
                    <div class="source-meta" style="display: flex; justify-content: space-between; font-size: 0.8rem; padding: 6px 10px;">
                        <span>${album.track_count} Tracks</span>
                        <span>${album.total_duration} mins</span>
                    </div>
                </div>
            `;
        }).join("");
    }
    updateGenericPagination("pagination-albums", currentAlbumPage, filteredAlbums.length, (dir) => {
        currentAlbumPage += dir;
        renderAlbumsPage();
    });
}

function renderArtistsPage() {
    const grid = document.getElementById("artists-grid");
    const startIndex = (currentArtistPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredArtists.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        grid.innerHTML = `<p class="empty-state" style="grid-column: 1/-1; padding: 40px;">No artists found.</p>`;
    } else {
        grid.innerHTML = paginatedItems.map(artist => {
            const coverImg = artist.cover_url
                ? `<img src="${artist.cover_url}" alt="Cover" style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover;">`
                : `<div style="width: 50px; height: 50px; border-radius: 50%; background: var(--bg-surface-alt); display: flex; align-items: center; justify-content: center; color: var(--text-muted);"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg></div>`;

            return `
                <div class="source-card" style="flex-direction: row; align-items: center; gap: 12px; cursor: pointer;" onclick="filterByArtist('${encodeURIComponent(artist.artist)}')">
                    ${coverImg}
                    <div style="min-width: 0; flex: 1;">
                        <h3 style="margin: 0 0 2px 0; font-size: 1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${artist.artist}</h3>
                        <div style="color: var(--text-muted); font-size: 0.8rem;">${artist.song_count} Songs • ${artist.album_count} Albums</div>
                    </div>
                </div>
            `;
        }).join("");
    }
    updateGenericPagination("pagination-artists", currentArtistPage, filteredArtists.length, (dir) => {
        currentArtistPage += dir;
        renderArtistsPage();
    });
}

function updateGenericPagination(containerId, page, totalLength, callback) {
    let container = document.getElementById(containerId);
    if (!container) {
        const parent = document.getElementById(containerId === 'pagination-albums' ? 'view-albums' : 'view-artists');
        container = document.createElement("div");
        container.id = containerId;
        container.className = "pagination-controls";
        container.style = "border-radius: 0 0 16px 16px; background: var(--bg-surface-alt); margin-top: 16px; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center;";
        container.innerHTML = `
            <button class="btn-secondary prev-btn">Previous</button>
            <span class="page-info" style="font-weight: 600; color: var(--text-muted);">Page 1</span>
            <button class="btn-secondary next-btn">Next</button>
        `;
        parent.appendChild(container);
    }
    const totalPages = Math.ceil(totalLength / itemsPerPage) || 1;
    container.querySelector(".page-info").textContent = `Page ${page} of ${totalPages} (${totalLength} items)`;
    
    const prevBtn = container.querySelector(".prev-btn");
    const nextBtn = container.querySelector(".next-btn");
    
    prevBtn.disabled = page === 1;
    nextBtn.disabled = page === totalPages;
    
    prevBtn.onclick = () => { if (page > 1) { callback(-1); window.scrollTo({top:0, behavior:'smooth'}); } };
    nextBtn.onclick = () => { if (page < totalPages) { callback(1); window.scrollTo({top:0, behavior:'smooth'}); } };
}

function filterByAlbum(albumName) {
    currentView = 'songs';
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-view="songs"]').classList.add('active');
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
    const decoded = decodeURIComponent(artistName);
    document.getElementById("library-search").value = decoded;
    filteredSongs = allSongs.filter(s => (s.artist || "").toLowerCase() === decoded.toLowerCase());
    currentSongPage = 1;
    renderActiveView();
}

// Tab Switching
document.querySelectorAll("#library-view-tabs .filter-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
        document.querySelectorAll("#library-view-tabs .filter-tab").forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        currentView = e.target.dataset.view;
        renderActiveView();
    });
});

// Sort Handler
document.getElementById("library-sort")?.addEventListener("change", async (e) => {
    currentSort = e.target.value;
    await loadLibraryData();
});

// Song Pagination
document.getElementById("btn-prev")?.addEventListener("click", () => {
    if (currentSongPage > 1) { currentSongPage--; renderSongsPage(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
});
document.getElementById("btn-next")?.addEventListener("click", () => {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage);
    if (currentSongPage < totalPages) { currentSongPage++; renderSongsPage(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
});

// Unified Search
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
                (s.album || "").toLowerCase().includes(q)
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

// Rescan & Deletion handlers remain standard
document.getElementById("btn-rescan")?.addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    try { await fetch("/api/library/rescan", { method: "POST" }); } 
    finally { setTimeout(() => { btn.disabled = false; loadLibraryData(); }, 1000); }
});

document.addEventListener("DOMContentLoaded", loadLibraryData);
