const search = document.getElementById("playlist-search");
const resultCount = document.getElementById("playlist-result-count");

function filterPlaylists() {
    const query = (search?.value || "").trim().toLowerCase();
    const cards = Array.from(document.querySelectorAll(".playlist-card"));
    let visible = 0;
    cards.forEach(card => {
        const matches = !query || card.dataset.playlistName.includes(query);
        card.hidden = !matches;
        if (matches) visible += 1;
    });
    if (resultCount) resultCount.textContent = `${visible} playlist${visible === 1 ? "" : "s"}`;
}

search?.addEventListener("input", filterPlaylists);

document.querySelectorAll(".playlist-sync-btn").forEach(button => {
    button.addEventListener("click", async () => {
        button.disabled = true;
        button.textContent = "Starting…";
        try {
            const response = await fetch(`/api/sources/${button.dataset.sourceId}/sync`, {
                method: "POST",
            });
            if (!response.ok) throw new Error("Playlist sync could not be started.");
            button.textContent = "Sync started";
        } catch (error) {
            alert(error.message);
            button.disabled = false;
            button.textContent = "↻ Resync";
        }
    });
});

const navidromeScan = document.getElementById("scan-navidrome");
navidromeScan?.addEventListener("click", async () => {
    navidromeScan.disabled = true;
    navidromeScan.textContent = "Requesting scan…";
    try {
        const response = await fetch("/api/navidrome/rescan?full_scan=false", {
            method: "POST",
        });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.detail || "Navidrome scan could not be started.");
        }
        navidromeScan.textContent = "Scan requested";
    } catch (error) {
        alert(error.message);
        navidromeScan.disabled = false;
        navidromeScan.textContent = "↻ Scan Navidrome";
    }
});
