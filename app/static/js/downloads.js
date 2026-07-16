let currentJobs = [];
let currentFilter = 'ALL';
let searchQuery = '';

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
            resultElement.innerHTML = `
                <div class="success-message">
                    <strong>Playlist queued successfully</strong><br>
                    ${data.summary.playlist_name}<br><br>
                    Queued: ${data.summary.queued}<br>
                    Already queued: ${data.summary.already_queued}<br>
                    Already owned: ${data.summary.owned}
                </div>
            `;
        } else if (data.status === "owned") {
            resultElement.innerHTML = `<div class="success-message">This track already exists in your library.</div>`;
        } else {
            resultElement.innerHTML = `<div class="success-message">Download queued successfully.</div>`;
        }
    } catch (error) {
        resultElement.innerHTML = `<div class="error-message">${error.message}</div>`;
    }
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

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center empty-state" style="padding: 40px;">No downloads found matching your criteria.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(job => {
        const status = (job.status || '').toUpperCase();
        const isFailed = status === 'FAILED' || status === 'CANCELLED';
        
        let statusHtml = `<span class="badge badge-${status.toLowerCase()}">${status}</span>`;
        if (status === 'RUNNING') {
            statusHtml = `<span class="badge badge-running"><span class="spinner" style="width:10px; height:10px; border-width:2px; margin-right:4px;"></span> Downloading</span>`;
        }

        const actionHtml = isFailed 
            ? `<button class="btn-retry" onclick="retryJob('${job.spotify_url}')">↻ Retry</button>` 
            : ``;

        return `
            <tr>
                <td style="padding-left: 24px;">${statusHtml}</td>
                <td style="font-weight: 600; color: #222;">${job.title ?? ""}</td>
                <td style="color: #666;">${job.artist ?? ""}</td>
                <td style="color: #666;">${job.album ?? ""}</td>
                <td style="text-align: right; padding-right: 24px;">${actionHtml}</td>
            </tr>
        `;
    }).join("");
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
    if (!response.ok) alert("Failed to clear history.");
});

// 5. Filter Listeners
document.querySelectorAll(".filter-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
        document.querySelectorAll(".filter-tab").forEach(t => t.classList.remove("active"));
        e.target.classList.add("active");
        currentFilter = e.target.dataset.filter;
        renderFilteredDownloads();
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
        currentJobs = JSON.parse(event.data);
        renderFilteredDownloads();
    };
    
    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

connectDownloadsSSE();
