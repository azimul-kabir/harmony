let allSongs = [];
let filteredSongs = [];
let currentPage = 1;
const itemsPerPage = 50;
let searchTimeout = null;

async function loadLibrary() {
    try {
        const response = await fetch("/api/library/songs");
        allSongs = await response.json();
        filteredSongs = allSongs; // Initialize without filter
        renderPage();
    } catch (e) {
        document.getElementById("library-body").innerHTML = `<tr><td colspan="4" style="color:red; text-align:center;">Failed to load library.</td></tr>`;
    }
}

function renderPage() {
    const tbody = document.getElementById("library-body");
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const paginatedItems = filteredSongs.slice(startIndex, endIndex);

    if (paginatedItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;">No songs found.</td></tr>`;
    } else {
        tbody.innerHTML = paginatedItems.map(s => `
            <tr>
                <td><input type="checkbox" class="song-check" data-id="${s.id}"></td>
                <td>${s.title || 'Unknown Title'}</td>
                <td>${s.artist || 'Unknown Artist'}</td>
                <td>${s.album || 'Unknown Album'}</td>
            </tr>
        `).join("");
    }

    updatePaginationUI();
    
    // Reset master checkbox state
    const selectAll = document.getElementById("select-all");
    if(selectAll) selectAll.checked = false;
    document.getElementById("delete-selected").disabled = true;
}

function updatePaginationUI() {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage) || 1;
    document.getElementById("page-info").textContent = `Page ${currentPage} of ${totalPages} (${filteredSongs.length} total)`;
    
    document.getElementById("btn-prev").disabled = currentPage === 1;
    document.getElementById("btn-next").disabled = currentPage === totalPages;
}

// Pagination Event Listeners
document.getElementById("btn-prev").addEventListener("click", () => {
    if (currentPage > 1) {
        currentPage--;
        renderPage();
    }
});

document.getElementById("btn-next").addEventListener("click", () => {
    const totalPages = Math.ceil(filteredSongs.length / itemsPerPage);
    if (currentPage < totalPages) {
        currentPage++;
        renderPage();
    }
});

// Debounced Search functionality
document.getElementById("library-search").addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    
    // Show loading state while user types
    if(e.target.value.trim().length > 0) {
        document.getElementById("library-body").innerHTML = `<tr><td colspan="4" style="text-align:center;">Searching...</td></tr>`;
    }

    searchTimeout = setTimeout(() => {
        const q = e.target.value.toLowerCase().trim();
        
        if (!q) {
            filteredSongs = allSongs;
        } else {
            filteredSongs = allSongs.filter(s => 
                (s.title || "").toLowerCase().includes(q) || 
                (s.artist || "").toLowerCase().includes(q) ||
                (s.album || "").toLowerCase().includes(q)
            );
        }
        
        currentPage = 1; // Reset to page 1 on new search
        renderPage();
    }, 300); // 300ms debounce
});

// Batch Delete logic
document.getElementById("delete-selected").addEventListener("click", async () => {
    const selected = Array.from(document.querySelectorAll(".song-check:checked"));
    if (selected.length === 0) return;
    
    if (!confirm(`Delete ${selected.length} song(s)? This cannot be undone.`)) return;

    for (const el of selected) {
        await fetch(`/api/library/song/${el.dataset.id}`, { method: "DELETE" });
    }
    
    loadLibrary(); // Refresh full dataset from server
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
loadLibrary();
