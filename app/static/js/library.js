let allSongs = [];
let filteredSongs = [];
let currentPage = 1;
const itemsPerPage = 50;
let searchTimeout = null;

async function loadLibrary() {
    try {
        const response = await fetch("/api/library/songs");
        if (!response.ok) throw new Error("Failed to fetch");
        
        allSongs = await response.json();
        
        // Sort alphabetically by artist, then title
        allSongs.sort((a, b) => {
            const artistA = (a.artist || "").toLowerCase();
            const artistB = (b.artist || "").toLowerCase();
            if (artistA < artistB) return -1;
            if (artistA > artistB) return 1;
            
            const titleA = (a.title || "").toLowerCase();
            const titleB = (b.title || "").toLowerCase();
            return titleA.localeCompare(titleB);
        });

        filteredSongs = allSongs;
        renderPage();
    } catch (e) {
        document.getElementById("library-body").innerHTML = `
            <tr>
                <td colspan="4" class="text-center empty-state" style="padding: 40px; color: #dc3545;">
                    Failed to load library data.
                </td>
            </tr>
        `;
    }
}

// Inside app/static/js/library.js, replace your renderPage() function with this:

function renderPage() {
    const tbody = document.getElementById("library-body");
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredSongs.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-center empty-state" style="padding: 40px;">
                    No tracks found.
                </td>
            </tr>
        `;
    } else {
        tbody.innerHTML = paginatedItems.map(s => {
            // NEW: Artwork HTML Generation
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

    updatePaginationUI();
    
    const selectAll = document.getElementById("select-all");
    if(selectAll) selectAll.checked = false;
    document.getElementById("delete-selected").disabled = true;
}

function updatePaginationUI() {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage) || 1;
    document.getElementById("page-info").textContent = `Page ${currentPage} of ${totalPages} (${filteredSongs.length} total tracks)`;
    
    document.getElementById("btn-prev").disabled = currentPage === 1;
    document.getElementById("btn-next").disabled = currentPage === totalPages;
}

// Pagination Event Listeners
document.getElementById("btn-prev").addEventListener("click", () => {
    if (currentPage > 1) {
        currentPage--;
        renderPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

document.getElementById("btn-next").addEventListener("click", () => {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage);
    if (currentPage < totalPages) {
        currentPage++;
        renderPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

// Debounced Search functionality
document.getElementById("library-search").addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    
    searchTimeout = setTimeout(() => {
        const q = e.target.value.toLowerCase().trim();
        
        if (!q) {
            filteredSongs = allSongs;
        } else {
            filteredSongs = allSongs.filter(s => 
                (s.title || "").toLowerCase().includes(q) || 
                (s.artist || "").toLowerCase().includes(q) ||
                (s.album || "").toLowerCase().includes(q) ||
                (s.filename || "").toLowerCase().includes(q)
            );
        }
        
        currentPage = 1; // Reset to page 1 on new search
        renderPage();
    }, 250); // 250ms debounce for snappy feeling
});

// Batch Delete logic
document.getElementById("delete-selected").addEventListener("click", async (e) => {
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
        await loadLibrary(); // Refresh full dataset from server
    }
});

// Rescan Library Logic
document.getElementById("btn-rescan").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="border-top-color: #1565c0;"></span> Scanning Storage...';
    
    try {
        await fetch("/api/library/rescan", { method: "POST" });
    } catch (err) {
        console.error("Rescan failed:", err);
    } finally {
        setTimeout(() => {
            btn.innerHTML = '↻ Rescan Library';
            btn.disabled = false;
            loadLibrary(); // Reload the table to show any new/deleted files
        }, 1000);
    }
});

// Enable/Disable delete button & Select All
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

// Init
document.addEventListener("DOMContentLoaded", loadLibrary);
