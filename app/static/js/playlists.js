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

async function generateAutoPlaylist(button) {
    const rule = button.dataset.autoRule;
    const limitInput = document.querySelector(`[data-auto-limit="${CSS.escape(rule)}"]`);
    const limit = Number(limitInput?.value || 50);
    const status = document.querySelector(`[data-auto-status="${CSS.escape(rule)}"]`);
    button.disabled = true;
    button.textContent = "Generating…";
    if (status) status.textContent = "Selecting songs and exporting M3U…";
    try {
        const response = await fetch(`/api/playlists/auto/${encodeURIComponent(rule)}/generate`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({limit, enabled: true}),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Auto-playlist could not be generated.");
        if (status) status.textContent = `${payload.exported_count} songs exported · ${payload.limit} song limit`;
        button.textContent = "Generated";
        window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
        if (status) status.textContent = error.message;
        button.disabled = false;
        button.textContent = "Try again";
    }
}

document.querySelectorAll(".auto-playlist-generate, .auto-playlist-refresh").forEach(button => {
    button.addEventListener("click", () => generateAutoPlaylist(button));
});

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

        let art;
        if (track.cover_url) {
            art = document.createElement("img");
            art.className = "playlist-track-artwork";
            art.src = track.cover_url;
            art.alt = "";
            art.loading = "lazy";
            art.addEventListener("error", () => {
                const placeholder = document.createElement("span");
                placeholder.className = "playlist-track-artwork playlist-track-artwork-placeholder";
                placeholder.textContent = "♪";
                art.replaceWith(placeholder);
            }, { once: true });
        } else {
            art = document.createElement("span");
            art.className = "playlist-track-artwork playlist-track-artwork-placeholder";
            art.textContent = "♪";
        }

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
        row.append(checkbox, position, art, copy, status);
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

const playlistArtworkDialog = document.getElementById("playlist-artwork-dialog");
const playlistArtworkPreview = document.getElementById("playlist-artwork-preview");
const playlistArtworkPlaceholder = document.getElementById("playlist-artwork-placeholder");
const playlistArtworkFile = document.getElementById("playlist-artwork-file");
const playlistArtworkSave = document.getElementById("playlist-artwork-save");
const playlistArtworkRemove = document.getElementById("playlist-artwork-remove");
const playlistArtworkStatus = document.getElementById("playlist-artwork-status");
let activeArtworkPlaylist = null;
let artworkObjectUrl = null;

function showArtworkPreview(url) {
    playlistArtworkPreview.hidden = !url;
    playlistArtworkPlaceholder.hidden = Boolean(url);
    if (url) playlistArtworkPreview.src = url;
    else playlistArtworkPreview.removeAttribute("src");
}

function openPlaylistArtwork(button) {
    activeArtworkPlaylist = {
        id: button.dataset.playlistId,
        name: button.dataset.playlistName,
        hasArtwork: button.dataset.artworkExists === "true",
        sourceCover: button.dataset.coverUrl,
    };
    document.getElementById("playlist-artwork-title").textContent = activeArtworkPlaylist.name;
    playlistArtworkFile.value = "";
    playlistArtworkSave.disabled = true;
    playlistArtworkRemove.disabled = !activeArtworkPlaylist.hasArtwork;
    playlistArtworkStatus.textContent = activeArtworkPlaylist.hasArtwork
        ? "This sidecar image overrides Navidrome’s generated playlist mosaic."
        : "Harmony saves this beside the M3U so Navidrome can read it.";
    showArtworkPreview(
        activeArtworkPlaylist.hasArtwork
            ? `/api/playlists/${activeArtworkPlaylist.id}/artwork?t=${Date.now()}`
            : activeArtworkPlaylist.sourceCover
    );
    playlistArtworkDialog.showModal();
}

document.querySelectorAll(".playlist-artwork-btn").forEach(button => {
    button.addEventListener("click", () => openPlaylistArtwork(button));
});

playlistArtworkFile?.addEventListener("change", () => {
    if (artworkObjectUrl) URL.revokeObjectURL(artworkObjectUrl);
    const file = playlistArtworkFile.files[0];
    playlistArtworkSave.disabled = !file;
    if (!file) {
        showArtworkPreview(activeArtworkPlaylist?.hasArtwork
            ? `/api/playlists/${activeArtworkPlaylist.id}/artwork?t=${Date.now()}`
            : activeArtworkPlaylist?.sourceCover);
        return;
    }
    artworkObjectUrl = URL.createObjectURL(file);
    showArtworkPreview(artworkObjectUrl);
    playlistArtworkStatus.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
});

playlistArtworkSave?.addEventListener("click", async () => {
    const file = playlistArtworkFile.files[0];
    if (!file || !activeArtworkPlaylist) return;
    const form = new FormData();
    form.append("artwork", file);
    playlistArtworkSave.disabled = true;
    playlistArtworkStatus.textContent = "Saving Navidrome sidecar…";
    try {
        const response = await fetch(`/api/playlists/${activeArtworkPlaylist.id}/artwork`, {
            method: "POST",
            body: form,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Playlist artwork could not be saved.");
        playlistArtworkStatus.textContent = payload.message;
        window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
        playlistArtworkStatus.textContent = error.message;
        playlistArtworkSave.disabled = false;
    }
});

playlistArtworkRemove?.addEventListener("click", async () => {
    if (!activeArtworkPlaylist) return;
    playlistArtworkRemove.disabled = true;
    playlistArtworkStatus.textContent = "Removing sidecar…";
    try {
        const response = await fetch(`/api/playlists/${activeArtworkPlaylist.id}/artwork`, {
            method: "DELETE",
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Playlist artwork could not be removed.");
        playlistArtworkStatus.textContent = payload.message;
        window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
        playlistArtworkStatus.textContent = error.message;
        playlistArtworkRemove.disabled = false;
    }
});

playlistArtworkDialog?.addEventListener("close", () => {
    if (artworkObjectUrl) URL.revokeObjectURL(artworkObjectUrl);
    artworkObjectUrl = null;
});

document.querySelectorAll(".playlist-delete-btn").forEach(button => {
    button.addEventListener("click", async () => {
        const sourceWarning = button.dataset.sourceExists === "true"
            ? "\n\nThis playlist still has a Source. A future source sync can create it again."
            : "";
        const confirmed = window.confirm(
            `Delete the playlist “${button.dataset.playlistName}” from Harmony?` +
            "\n\nIts M3U file will be removed. Downloaded songs will remain in your Library." +
            sourceWarning
        );
        if (!confirmed) return;

        button.disabled = true;
        button.textContent = "Deleting…";
        try {
            const response = await fetch(`/api/playlists/${button.dataset.playlistId}`, {
                method: "DELETE",
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || "Playlist could not be deleted.");
            button.closest(".playlist-card")?.remove();
            filterPlaylists();
            if (!document.querySelector(".playlist-card")) window.location.reload();
        } catch (error) {
            window.alert(error.message);
            button.disabled = false;
            button.textContent = "Delete playlist";
        }
    });
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
