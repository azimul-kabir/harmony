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

const navSelect = document.getElementById("navidrome-playlist-select");
const navRefresh = document.getElementById("navidrome-playlist-refresh");
const loveButton = document.getElementById("navidrome-love-all");
const unloveButton = document.getElementById("navidrome-unlove-all");
const loveStatus = document.getElementById("navidrome-love-progress");
const loveProgress = document.getElementById("navidrome-love-progress-bar");
let navPlaylists = [];
let navLoadController = null;

function setNavidromeStatus(message, state = "idle") {
    const copy = loveStatus?.querySelector(".navidrome-status-copy");
    if (copy) copy.textContent = message;
    else if (loveStatus) loveStatus.textContent = message;
    loveStatus?.classList.remove("is-loading", "is-error", "is-ready");
    if (state !== "idle") loveStatus?.classList.add(`is-${state}`);
}

async function loadNavidromePlaylists() {
    navLoadController?.abort();
    const controller = new AbortController();
    navLoadController = controller;
    const timeout = window.setTimeout(() => controller.abort(), 16000);
    navRefresh.disabled = true;
    navSelect.disabled = true;
    loveButton.disabled = true;
    unloveButton.disabled = true;
    navSelect.replaceChildren(new Option("Loading playlists…", ""));
    setNavidromeStatus("Connecting to Navidrome…", "loading");
    try {
        const response = await fetch("/api/navidrome/playlists", {signal: controller.signal});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail?.message || "Navidrome playlists are unavailable.");
        navPlaylists = Array.isArray(payload.playlists) ? payload.playlists : [];
        navSelect.replaceChildren(new Option(navPlaylists.length ? "Select a playlist…" : "No playlists found", ""));
        navPlaylists.forEach(item => navSelect.add(new Option(`${item.name} · ${item.track_count} tracks`, item.id)));
        navSelect.disabled = navPlaylists.length === 0;
        setNavidromeStatus(navPlaylists.length ? `${navPlaylists.length} playlist${navPlaylists.length === 1 ? "" : "s"} ready` : "Navidrome returned no playlists.", navPlaylists.length ? "ready" : "idle");
    } catch (error) {
        navPlaylists = [];
        navSelect.replaceChildren(new Option("Unable to load playlists", ""));
        setNavidromeStatus(error.name === "AbortError" ? "Navidrome took too long to respond. Try again." : error.message, "error");
    } finally {
        window.clearTimeout(timeout);
        navRefresh.disabled = false;
    }
}
navSelect?.addEventListener("change", () => {
    loveButton.disabled = unloveButton.disabled = !navSelect.value;
    const item = navPlaylists.find(playlist => playlist.id === navSelect.value);
    setNavidromeStatus(item ? `${item.track_count} track${item.track_count === 1 ? "" : "s"} selected` : `${navPlaylists.length} playlist${navPlaylists.length === 1 ? "" : "s"} ready`, "ready");
});
navRefresh?.addEventListener("click", loadNavidromePlaylists);

function pollLoveJob(id) {
    window.setTimeout(async () => {
        const response = await fetch(`/api/navidrome/jobs/${id}`); const job = await response.json();
        loveProgress.max = Math.max(1, job.total_tracks); loveProgress.value = job.processed_tracks;
        setNavidromeStatus(`${job.status.replaceAll("_", " ")} · ${job.processed_tracks}/${job.total_tracks} tracks · batch ${job.current_batch}/${job.total_batches}` + (job.safe_error_message ? ` · ${job.safe_error_message}` : ""), "loading");
        if (["completed", "partially_completed", "failed", "cancelled"].includes(job.status)) { loveButton.disabled = unloveButton.disabled = false; return; }
        pollLoveJob(id);
    }, 600);
}
async function startLove(operation) {
    const item = navPlaylists.find(p => p.id === navSelect.value); if (!item) return;
    const destructive = operation === "unlove";
    const message = destructive
        ? `Remove Loved status from every current track in “${item.name}” (${item.track_count} tracks) for the configured Navidrome user?\n\nThis is destructive and does not restore an earlier state.`
        : `Mark every current track in “${item.name}” (${item.track_count} tracks) as Loved for the configured Navidrome user?`;
    if (!window.confirm(message)) return;
    loveButton.disabled = unloveButton.disabled = true; loveProgress.hidden = false; setNavidromeStatus("Queueing operation…", "loading");
    const response = await fetch(`/api/navidrome/playlists/${encodeURIComponent(item.id)}/${operation}`, {method: "POST"}); const job = await response.json();
    if (!response.ok) { setNavidromeStatus(job.detail?.message || "Operation could not be queued.", "error"); loveButton.disabled = unloveButton.disabled = false; return; }
    pollLoveJob(job.job_id);
}
loveButton?.addEventListener("click", () => startLove("love"));
unloveButton?.addEventListener("click", () => startLove("unlove"));
if (navSelect) loadNavidromePlaylists();

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
const navidromeScanStatus = document.getElementById("scan-navidrome-status");

function navidromeErrorMessage(payload, fallback) {
    if (typeof payload?.detail === "string") return payload.detail;
    if (typeof payload?.detail?.message === "string") return payload.detail.message;
    return fallback;
}

function setNavidromeScanState(label, message, disabled) {
    navidromeScan.textContent = label;
    navidromeScan.disabled = disabled;
    if (navidromeScanStatus) navidromeScanStatus.textContent = message;
}

async function pollNavidromeScan(initiallyScanning = false) {
    // Navidrome may acknowledge startScan before its scanner flips to active.
    // Poll long enough to show a real completion state instead of leaving the
    // button permanently disabled after the first click.
    let observedScanning = initiallyScanning;
    for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        const response = await fetch("/api/navidrome/status");
        const status = await response.json().catch(() => ({}));
        if (!response.ok || !status.reachable) {
            throw new Error(status.error || "Navidrome scan status is unavailable.");
        }
        if (status.scanning) {
            observedScanning = true;
            setNavidromeScanState(
                "Scanning Navidrome…",
                `${Number(status.scan_count || 0).toLocaleString()} items processed`,
                true,
            );
            continue;
        }
        if (observedScanning || attempt >= 2) {
            setNavidromeScanState("↻ Scan Navidrome", "Navidrome scan completed.", false);
            return;
        }
    }
    setNavidromeScanState("↻ Scan Navidrome", "Scan is still running; check the dashboard for status.", false);
}

navidromeScan?.addEventListener("click", async () => {
    setNavidromeScanState("Requesting scan…", "Sending scan request to Navidrome…", true);
    try {
        const response = await fetch("/api/navidrome/rescan?full_scan=false", {
            method: "POST",
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(navidromeErrorMessage(payload, "Navidrome scan could not be started."));
        }
        if (payload.accepted !== true) throw new Error("Navidrome did not accept the scan request.");
        setNavidromeScanState("Scan requested", "Navidrome accepted the library scan.", true);
        await pollNavidromeScan(Boolean(payload.scanning));
    } catch (error) {
        setNavidromeScanState("↻ Scan Navidrome", error.message, false);
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
