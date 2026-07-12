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
        let icon = "•";

        switch (job.status) {
            case "COMPLETED":
                icon = "✅";
                break;
            case "FAILED":
                icon = "❌";
                break;
            case "RUNNING":
                icon = "⬇️";
                break;
            case "QUEUED":
                icon = "⏳";
                break;
            case "SKIPPED":
                icon = "⏭️";
                break;
        }

        return `
            <div class="activity-item">
                <strong>${icon} ${job.title ?? "Unknown Title"}</strong><br>
                <small>${job.artist ?? "Unknown Artist"}</small>
            </div>
        `;
    }).join("");
}