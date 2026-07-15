const downloadForm = document.getElementById("download-form");

if (downloadForm) {
    downloadForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const input = document.getElementById("spotify-url");
        const result = document.getElementById("download-result");

        result.textContent = "Downloading...";

        try {
            const response = await fetch("/api/downloads", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    url: input.value,
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Download failed.");
            }

            if (data.summary) {
                result.innerHTML = `
                    <div class="success-message">
                        <strong>Playlist queued successfully</strong><br>
                        ${data.summary.playlist_name}<br><br>
                        Queued: ${data.summary.queued}<br>
                        Already queued: ${data.summary.already_queued}<br>
                        Already owned: ${data.summary.owned}
                    </div>
                `;
            } else if (data.status === "owned") {
                result.innerHTML = `
                    <div class="success-message">
                        This track already exists in your library.
                    </div>
                `;
            } else {
                result.innerHTML = `
                    <div class="success-message">
                        Download queued successfully.
                    </div>
                `;
            }

            input.value = "";
        } catch (error) {
            result.innerHTML = `
                <div class="error-message">
                    ${error.message}
                </div>
            `;
        }
    });
}

function renderDownloads(jobs) {
    const tbody = document.getElementById("downloads-body");
    if (!tbody) return;

    if (!jobs || jobs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4">No downloads yet.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = jobs.map(job => `
        <tr>
            <td>
                <span class="badge badge-${job.status.toLowerCase()}">
                    ${job.status}
                </span>
            </td>
            <td>${job.title ?? ""}</td>
            <td>${job.artist ?? ""}</td>
            <td>${job.album ?? ""}</td>
        </tr>
    `).join("");
}

function connectDownloadsSSE() {
    // Only connect if we are actually on the downloads page
    if (!document.getElementById("downloads-body")) {
        return;
    }

    const eventSource = new EventSource("/api/downloads/stream");

    eventSource.onmessage = function(event) {
        const jobs = JSON.parse(event.data);
        renderDownloads(jobs);
    };

    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

// Initialize the stream on page load
connectDownloadsSSE();
