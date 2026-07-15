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
            submitBtn.textContent = "Invalid Spotify URL";
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
        result.textContent = "Downloading...";
        
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
    if (currentFilter !== 'ALL') {
        filtered = filtered.filter(job => (job.status || '').toUpperCase() === currentFilter);
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
        tbody.innerHTML = `<tr><td colspan="5">No downloads match your filters.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(job => {
        const isFailed = (job.status || '').toUpperCase() === 'FAILED';
        const actionHtml = isFailed 
            ? `<button class="btn-retry" onclick="retryJob('${job.spotify_url}')">↻ Retry</button>` 
            : ``;

        return `
            <tr>
                <td><span class="badge badge-${(job.status || '').toLowerCase()}">${job.status}</span></td>
                <td>${job.title ?? ""}</td>
                <td>${job.artist ?? ""}</td>
                <td>${job.album ?? ""}</td>
                <td>${actionHtml}</td>
            </tr>
        `;
    }).join("");
}

// 4. Action Handlers
window.retryJob = async function(url) {
    if (!url) return;
    const resultElement = document.getElementById("download-result");
    resultElement.innerHTML = `<div class="success-message">Retrying download...</div>`;
    await queueSpotifyUrl(url, resultElement);
};

document.getElementById("clear-history-btn")?.addEventListener("click", async () => {
    if (!confirm("Are you sure you want to clear all completed and failed history?")) return;
    
    const response = await fetch("/api/downloads/clear", { method: "POST" });
    if (!response.ok) alert("Failed to clear history.");
});

// 5. Filter Listeners
document.querySelectorAll(".filter-pill").forEach(pill => {
    pill.addEventListener("click", (e) => {
        document.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
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
