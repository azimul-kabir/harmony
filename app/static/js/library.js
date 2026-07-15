let songs = [];

async function loadLibrary() {
    const response = await fetch("/api/library/songs");
    songs = await response.json();
    renderLibrary(songs);
}

function renderLibrary(data) {
    const tbody = document.getElementById("library-body");
    tbody.innerHTML = data.map(s => `
        <tr>
            <td><input type="checkbox" class="song-check" data-id="${s.id}"></td>
            <td>${s.title}</td>
            <td>${s.artist}</td>
            <td>${s.album}</td>
        </tr>
    `).join("");
}

// Search functionality
document.getElementById("library-search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = songs.filter(s => 
        s.title.toLowerCase().includes(q) || 
        s.artist.toLowerCase().includes(q) ||
        s.album.toLowerCase().includes(q)
    );
    renderLibrary(filtered);
});

// Batch Delete logic
document.getElementById("delete-selected").addEventListener("click", async () => {
    const selected = Array.from(document.querySelectorAll(".song-check:checked"));
    if (selected.length === 0) return;
    
    if (!confirm(`Delete ${selected.length} song(s)? This cannot be undone.`)) return;

    for (const el of selected) {
        await fetch(`/api/library/song/${el.dataset.id}`, { method: "DELETE" });
    }
    
    loadLibrary(); // Refresh view
});

// Enable/Disable delete button
document.addEventListener("change", (e) => {
    if (e.target.classList.contains("song-check") || e.target.id === "select-all") {
        const count = document.querySelectorAll(".song-check:checked").length;
        document.getElementById("delete-selected").disabled = count === 0;
    }
});

loadLibrary();
