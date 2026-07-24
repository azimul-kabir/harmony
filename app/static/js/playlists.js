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

const playlistDialog = document.getElementById("playlist-tracks-dialog");
const playlistTrackList = document.getElementById("playlist-track-list");
const playlistSelectAll = document.getElementById("playlist-select-all");
const playlistDeleteButton = document.getElementById("playlist-delete-selected");
const playlistSelection = new Set();
let activePlaylist = null;
let playlistBulkPoll = null;

function terminalBulkStatus(status) {
    return ["completed", "completed_with_errors", "failed", "cancelled"].includes(status);
}

function updatePlaylistSelection() {
    const selectable = activePlaylist?.tracks.filter(track => track.selectable) || [];
    const selectedCount = playlistSelection.size;
    playlistSelectAll.checked = selectable.length > 0 && selectedCount === selectable.length;
    playlistSelectAll.indeterminate = selectedCount > 0 && selectedCount < selectable.length;
    playlistSelectAll.disabled = selectable.length === 0;
    playlistDeleteButton.disabled = selectedCount === 0;
    playlistDeleteButton.textContent = selectedCount
        ? `Delete ${selectedCount} selected file${selectedCount === 1 ? "" : "s"}`
        : "Delete selected files";
}

function renderPlaylistTracks(payload) {
    activePlaylist = payload;
    playlistSelection.clear();
    document.getElementById("playlist-tracks-title").textContent = payload.name;
    document.getElementById("playlist-tracks-summary").textContent =
        `${payload.track_count} source tracks · ${payload.deletable_count} available to delete from Harmony`;
    playlistTrackList.replaceChildren();

    payload.tracks.forEach(track => {
        const row = document.createElement("label");
        row.className = `playlist-track-row${track.selectable ? "" : " is-unavailable"}`;
        row.setAttribute("role", "listitem");

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.disabled = !track.selectable;
        checkbox.checked = false;
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) playlistSelection.add(track.song_id);
            else playlistSelection.delete(track.song_id);
            updatePlaylistSelection();
        });

        const position = document.createElement("span");
        position.className = "playlist-track-position";
        position.textContent = track.position;

        const copy = document.createElement("span");
        copy.className = "playlist-track-copy";
        const title = document.createElement("strong");
        title.textContent = track.title;
        const detail = document.createElement("small");
        detail.textContent = `${track.artist}${track.album ? ` · ${track.album}` : ""}`;
        copy.append(title, detail);

        const status = document.createElement("span");
        status.className = "playlist-track-status";
        status.textContent = track.selectable
            ? "In library"
            : track.availability === "missing" ? "Already missing" : "Not downloaded";
        row.append(checkbox, position, copy, status);
        playlistTrackList.appendChild(row);
    });
    updatePlaylistSelection();
}

async function openPlaylistTracks(button) {
    clearTimeout(playlistBulkPoll);
    delete playlistDialog.dataset.refresh;
    activePlaylist = null;
    playlistSelection.clear();
    playlistTrackList.replaceChildren();
    document.getElementById("playlist-tracks-title").textContent = button.dataset.playlistName;
    document.getElementById("playlist-tracks-summary").textContent = "Loading songs…";
    document.getElementById("playlist-delete-progress").hidden = true;
    playlistDeleteButton.disabled = true;
    playlistDialog.showModal();
    try {
        const response = await fetch(`/api/playlists/${button.dataset.playlistId}/tracks`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Playlist songs could not be loaded.");
        renderPlaylistTracks(payload);
    } catch (error) {
        document.getElementById("playlist-tracks-summary").textContent = error.message;
    }
}

document.querySelectorAll(".playlist-manage-btn").forEach(button => {
    button.addEventListener("click", () => openPlaylistTracks(button));
});

playlistSelectAll?.addEventListener("change", event => {
    activePlaylist?.tracks.filter(track => track.selectable).forEach(track => {
        if (event.target.checked) playlistSelection.add(track.song_id);
        else playlistSelection.delete(track.song_id);
    });
    playlistTrackList.querySelectorAll("input[type='checkbox']:not(:disabled)").forEach(checkbox => {
        checkbox.checked = event.target.checked;
    });
    updatePlaylistSelection();
});

async function pollPlaylistDeletion(taskId) {
    try {
        const response = await fetch(`/api/library/bulk/${taskId}`);
        const task = await response.json();
        if (!response.ok) throw new Error(task.detail || "Deletion progress is unavailable.");
        document.getElementById("playlist-delete-progress-bar").value = task.progress;
        document.getElementById("playlist-delete-progress-text").textContent =
            terminalBulkStatus(task.status)
                ? `${task.completed} deleted · ${task.failed} failed`
                : `${task.processed} of ${task.total} processed`;
        if (terminalBulkStatus(task.status)) {
            playlistDialog.dataset.refresh = "true";
            playlistDeleteButton.disabled = true;
            return;
        }
        playlistBulkPoll = window.setTimeout(() => pollPlaylistDeletion(taskId), 700);
    } catch (error) {
        document.getElementById("playlist-delete-progress-text").textContent = error.message;
        playlistBulkPoll = window.setTimeout(() => pollPlaylistDeletion(taskId), 1500);
    }
}

playlistDeleteButton?.addEventListener("click", async () => {
    const count = playlistSelection.size;
    if (!count) return;
    const confirmed = window.confirm(
        `Permanently delete ${count} selected audio file${count === 1 ? "" : "s"} from Harmony's library?\n\n` +
        "These songs will disappear from every playlist and album that uses them. " +
        "Harmony retains missing-file records for audit and recovery."
    );
    if (!confirmed) return;

    playlistDeleteButton.disabled = true;
    document.getElementById("playlist-delete-progress").hidden = false;
    document.getElementById("playlist-delete-progress-text").textContent = "Queueing deletion…";
    try {
        const response = await fetch("/api/library/bulk", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                operation: "delete",
                song_ids: [...playlistSelection],
                options: {},
            }),
        });
        const task = await response.json();
        if (!response.ok) throw new Error(task.detail || "Deletion could not be started.");
        pollPlaylistDeletion(task.id);
    } catch (error) {
        document.getElementById("playlist-delete-progress-text").textContent = error.message;
        updatePlaylistSelection();
    }
});

playlistDialog?.addEventListener("close", () => {
    clearTimeout(playlistBulkPoll);
    if (playlistDialog.dataset.refresh === "true") window.location.reload();
});
