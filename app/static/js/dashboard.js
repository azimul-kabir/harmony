async function refreshDashboard() {
    const response = await fetch("/api/dashboard");

    if (!response.ok) {
        return;
    }

    const stats = await response.json();

    document.getElementById("songs-count").textContent =
        stats.songs;

    document.getElementById("downloads-count").textContent =
        stats.downloads;

    document.getElementById("sources-count").textContent =
        stats.sources;

    document.getElementById("failed-count").textContent =
        stats.failed;
}

if (document.getElementById("songs-count")) {
    refreshDashboard();
    refreshActivity();

    setInterval(() => {
        refreshDashboard();
        refreshActivity();
    }, 5000);
}

async function refreshActivity() {
    const container = document.getElementById("recent-activity");

    if (!container) {
        return;
    }

    const response = await fetch("/api/dashboard/activity");

    if (!response.ok) {
        return;
    }

    const jobs = await response.json();

    if (jobs.length === 0) {
        container.innerHTML = "<p>No recent activity.</p>";
        return;
    }

    container.innerHTML = jobs.map(job => {
        console.log(job.status);
        
        const status = (job.status ?? "").toUpperCase();

        let icon = "🎵";
        let label = status;

        switch (status) {
            case "COMPLETED":
                icon = "✅";
                label = "Downloaded";
                break;

            case "FAILED":
                icon = "❌";
                label = "Failed";
                break;

            case "RUNNING":
                icon = "⬇️";
                label = "Downloading";
                break;

            case "QUEUED":
                icon = "⏳";
                label = "Queued";
                break;

            case "SKIPPED":
                icon = "⏭️";
                label = "Skipped";
                break;
        }

        return `
            <div class="activity-item">

                <div class="activity-header">
                    <span class="activity-icon">${icon}</span>
                    <span class="activity-status">${label}</span>
                </div>

                <div class="activity-title">
                    ${job.title ?? "Unknown Title"}
                </div>

                <div class="activity-artist">
                    ${job.artist ?? "Unknown Artist"}
                </div>

            </div>
        `;
    }).join("");
}