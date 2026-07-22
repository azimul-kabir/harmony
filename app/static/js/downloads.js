let currentJobs = [];
const DOWNLOAD_FILTERS = new Set(["ALL", "ACTIVE", "COMPLETED", "FAILED"]);
const requestedStatus = new URLSearchParams(window.location.search).get("status")?.toUpperCase();
let currentFilter = DOWNLOAD_FILTERS.has(requestedStatus) ? requestedStatus : "ALL";
let searchQuery = '';

function setDownloadText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = Number(value || 0).toLocaleString();
}

function setDownloadFilter(filter) {
    currentFilter = DOWNLOAD_FILTERS.has(filter) ? filter : "ALL";
    document.querySelectorAll(".filter-tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.filter === currentFilter);
    });
    const url = new URL(window.location.href);
    if (currentFilter === "ALL") url.searchParams.delete("status");
    else url.searchParams.set("status", currentFilter.toLowerCase());
    window.history.replaceState({}, "", url);
    renderFilteredDownloads();
}

// 1. Smart URL Validation
const urlInput = document.getElementById("spotify-url");
const submitBtn = document.getElementById("download-submit-btn");

if (urlInput) {
    urlInput.addEventListener("input", (e) => {
        const val = e.target.value.trim();
        if (val.length > 0 && !val.includes("open.spotify.com")) {
            urlInput.classList.add("invalid");
            submitBtn.disabled = true;
            submitBtn.textContent = "Invalid URL";
        } else {
            urlInput.classList.remove("invalid");
            submitBtn.disabled = false;
            submitBtn.textContent = "Download";
        }
    });
}

// 2. Download Form Submission
const downloadForm = document.getElementById("download-form");
if (downloadForm) {
    downloadForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const result = document.getElementById("download-result");
        result.innerHTML = '<div class="success-message"><span class="spinner" style="border-top-color:#1565c0;"></span> Processing...</div>';
        
        await queueSpotifyUrl(urlInput.value, result);
        urlInput.value = "";
    });
}

async function queueSpotifyUrl(url, resultElement) {
    try {
        const response = await fetch("/api/downloads", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url }),
        });
        
        const data = await response.json();
        
        if (!response.ok) throw new Error(data.detail || "Download failed.");
        
        if (data.summary) {
            showDownloadResult(resultElement, "success", [
                "Playlist queued successfully",
                data.summary.playlist_name,
                `Queued: ${data.summary.queued}`,
                `Already queued: ${data.summary.already_queued}`,
                `Already owned: ${data.summary.owned}`,
            ]);
        } else if (data.status === "owned") {
            showDownloadResult(resultElement, "success", ["This track already exists in your library."]);
        } else {
            showDownloadResult(resultElement, "success", ["Download queued successfully."]);
        }
    } catch (error) {
        showDownloadResult(resultElement, "error", [error.message || "Download failed."]);
    }
}

function showDownloadResult(container, type, lines) {
    const message = document.createElement("div");
    message.className = type === "error" ? "error-message" : "success-message";
    const visibleLines = lines.filter((line) => line != null && line !== "");
    visibleLines.forEach((line, index) => {
        const text = document.createElement(index === 0 && type === "success" ? "strong" : "span");
        text.textContent = String(line);
        message.appendChild(text);
        if (index < visibleLines.length - 1) message.appendChild(document.createElement("br"));
    });
    container.replaceChildren(message);
}

// 3. Client-Side Rendering & Filtering
function renderFilteredDownloads() {
    const tbody = document.getElementById("downloads-body");
    if (!tbody) return;

    // Apply Status Filter
    let filtered = currentJobs;
    if (currentFilter === 'ACTIVE') {
        filtered = filtered.filter(j => ['RUNNING', 'QUEUED'].includes((j.status || '').toUpperCase()));
    } else if (currentFilter === 'COMPLETED') {
        filtered = filtered.filter(j => ['COMPLETED', 'SKIPPED'].includes((j.status || '').toUpperCase()));
    } else if (currentFilter === 'FAILED') {
        filtered = filtered.filter(j => ['FAILED', 'CANCELLED'].includes((j.status || '').toUpperCase()));
    }

    // Apply Search Filter
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        filtered = filtered.filter(job => 
            (job.title || '').toLowerCase().includes(q) || 
            (job.artist || '').toLowerCase().includes(q) ||
            (job.album || '').toLowerCase().includes(q)
        );
    }

    const jobIds = new Set(filtered.map((job) => String(job.id)));
    tbody.querySelectorAll("tr[data-download-id]").forEach((row) => {
        if (!jobIds.has(row.dataset.downloadId)) row.remove();
    });

    if (filtered.length === 0) {
        const empty = document.createElement("tr");
        empty.innerHTML = '<td colspan="5" class="text-center empty-state" style="padding: 40px;">No downloads found matching your criteria.</td>';
        tbody.replaceChildren(empty);
        updateVisibleDownloadCount(0);
        return;
    }

    tbody.querySelectorAll("tr:not([data-download-id])").forEach((row) => row.remove());
    filtered.forEach((job) => patchDownloadRow(tbody, job));
    updateVisibleDownloadCount(filtered.length);
}

function updateVisibleDownloadCount(visible) {
    const label = document.getElementById("downloads-visible-count");
    if (!label) return;
    label.textContent = `${visible.toLocaleString()} of ${currentJobs.length.toLocaleString()} recent downloads shown`;
}

function patchDownloadRow(tbody, job) {
    let row = tbody.querySelector(`tr[data-download-id="${job.id}"]`);
    if (!row) {
        row = document.createElement("tr");
        row.dataset.downloadId = String(job.id);
        row.innerHTML = '<td class="download-status-cell"></td><td><div class="download-song-cell"></div></td><td class="download-artist-cell"></td><td class="download-album-cell"></td><td class="download-actions-cell"></td>';
        tbody.appendChild(row);
    }
    const status = String(job.status || "").toUpperCase();
    const isFailed = ["FAILED", "CANCELLED"].includes(status);
    const statusCell = row.querySelector(".download-status-cell");
    statusCell.replaceChildren();
    const badge = document.createElement("span");
    badge.className = `badge badge-${status.toLowerCase()}`;
    badge.textContent = status === "RUNNING" ? "Downloading" : status || "Unknown";
    statusCell.appendChild(badge);

    const songCell = row.querySelector(".download-song-cell");
    songCell.replaceChildren();
    if (job.cover_url) {
        const image = document.createElement("img");
        image.className = "download-artwork";
        image.src = job.cover_url;
        image.alt = "";
        songCell.appendChild(image);
    } else {
        const placeholder = document.createElement("span");
        placeholder.className = "download-artwork-placeholder";
        placeholder.textContent = "♫";
        placeholder.setAttribute("aria-hidden", "true");
        songCell.appendChild(placeholder);
    }
    const details = document.createElement("div");
    details.style.minWidth = "0";
    const title = document.createElement("strong");
    title.className = "download-title";
    title.textContent = job.title || "Unknown title";
    details.appendChild(title);
    if (isFailed && job.error) {
        const error = document.createElement("small");
        error.className = "download-error";
        error.title = job.error;
        error.textContent = job.error;
        details.appendChild(error);
    }
    songCell.appendChild(details);
    row.querySelector(".download-artist-cell").textContent = job.artist || "—";
    row.querySelector(".download-album-cell").textContent = job.album || "—";
    const actions = row.querySelector(".download-actions-cell");
    actions.replaceChildren();
    if (isFailed && job.spotify_url) {
        const retry = document.createElement("button");
        retry.className = "btn-retry";
        retry.type = "button";
        retry.textContent = "Retry";
        retry.addEventListener("click", () => retryJob(job.spotify_url));
        actions.appendChild(retry);
    }
}

// 4. Action Handlers
window.retryJob = async function(url) {
    if (!url) return;
    const resultElement = document.getElementById("download-result");
    resultElement.innerHTML = '<div class="success-message"><span class="spinner" style="border-top-color:#1565c0;"></span> Retrying download...</div>';
    await queueSpotifyUrl(url, resultElement);
}

document.getElementById("clear-history-btn")?.addEventListener("click", async () => {
    if (!confirm("Are you sure you want to clear all completed and failed history?")) return;
    const response = await fetch("/api/downloads/clear", { method: "POST" });
    const result = document.getElementById("download-result");
    if (!response.ok) {
        showDownloadResult(result, "error", ["Failed to clear history."]);
        return;
    }
    showDownloadResult(result, "success", ["Completed, failed, skipped, and cancelled history cleared."]);
});

// 5. Filter Listeners
document.querySelectorAll(".filter-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
        setDownloadFilter(e.target.dataset.filter);
    });
});

document.getElementById("search-input")?.addEventListener("input", (e) => {
    searchQuery = e.target.value.trim();
    renderFilteredDownloads();
});

// 6. SSE Connection
function connectDownloadsSSE() {
    if (!document.getElementById("downloads-body")) return;
    const eventSource = new EventSource("/api/downloads/stream");
    
    eventSource.onmessage = function(event) {
        const snapshot = JSON.parse(event.data);
        currentJobs = snapshot.jobs || [];
        const summary = snapshot.summary || {};
        setDownloadText("downloads-running", summary.running);
        setDownloadText("downloads-queued", summary.queued);
        setDownloadText("downloads-completed", summary.completed);
        setDownloadText("downloads-attention", summary.attention);
        renderFilteredDownloads();
    };
    
    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

document.querySelectorAll("[data-summary-filter]").forEach((card) => {
    card.addEventListener("click", () => setDownloadFilter(card.dataset.summaryFilter));
});

setDownloadFilter(currentFilter);
connectDownloadsSSE();
