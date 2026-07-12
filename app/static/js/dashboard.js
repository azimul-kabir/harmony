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
    refreshTasks();

    setInterval(() => {
        refreshDashboard();
        refreshActivity();
        refreshTasks();
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


function taskStatus(status) {

    switch ((status ?? "").toUpperCase()) {

        case "RUNNING":
            return "⬇️ Downloading";

        case "QUEUED":
            return "⏳ Queued";

        case "COMPLETED":
            return "✅ Completed";

        case "FAILED":
            return "❌ Failed";

        default:
            return status;
    }

}


async function refreshTasks() {

    const container =
        document.getElementById("active-tasks");

    if (!container) {
        return;
    }

    const response =
        await fetch("/api/tasks");

    if (!response.ok) {
        return;
    }

    const tasks = await response.json();

    if (tasks.length === 0) {
        container.innerHTML =
            "<p>No active tasks.</p>";
        return;
    }

    container.innerHTML = tasks.map(task => {

        const finished =
            task.completed +
            task.failed +
            task.skipped;

        const percent =
            task.total === 0
                ? 0
                : (finished / task.total) * 100;

        return `
            <div class="task-item">

                <div class="task-title">
                    🎵 ${task.name}
                </div>

                <div class="task-status">
                    ${taskStatus(task.status)}
                </div>

                <div class="task-progress-bar">
                    <div
                        class="task-progress-fill"
                        style="width:${percent}%">
                    </div>
                </div>

                <div class="task-progress">
                    ${finished} / ${task.total}
                </div>

                ${
                    task.current
                        ? `<div class="task-current">
                            Now downloading: ${task.current}
                        </div>`
                        : ""
                }

            </div>
        `;
    }).join("");

}