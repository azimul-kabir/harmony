async function refreshDashboard() {
    const response = await fetch("/api/dashboard");

    if (!response.ok) {
        return;
    }

    const stats = await response.json();

    document.getElementById("songs-count").textContent = stats.songs;
    document.getElementById("downloads-count").textContent = stats.downloads;
    document.getElementById("sources-count").textContent = stats.sources;
    document.getElementById("failed-count").textContent = stats.failed;
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
            case "PAUSED":
                icon = "⏸️";
                label = "Paused";
                break;
            case "CANCELLED":
                icon = "🛑";
                label = "Cancelled";
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
        case "PAUSED":
            return "⏸️ Paused";
        case "CANCELLED":
            return "🛑 Cancelled";
        default:
            return status;
    }
}

// New function to handle the button clicks
async function handleTaskAction(taskId, action) {
    const response = await fetch(`/api/tasks/${taskId}/${action}`, {
        method: "POST"
    });
    
    if (response.ok) {
        // Instantly refresh the UI to show the new state
        refreshTasks(); 
    }
}

async function refreshTasks() {
    const container = document.getElementById("active-tasks");

    if (!container) {
        return;
    }

    const response = await fetch("/api/tasks");

    if (!response.ok) {
        return;
    }

    const tasks = await response.json();

    if (tasks.length === 0) {
        container.innerHTML = "<p>No active tasks.</p>";
        return;
    }

    container.innerHTML = tasks.map(task => {
        const finished = task.completed + task.failed + task.skipped;
        const percent = task.total === 0 ? 0 : (finished / task.total) * 100;

        // Generate dynamic control buttons based on task status
        let actionButtons = "";
        const taskState = (task.status ?? "").toUpperCase();
        
        if (taskState === "RUNNING" || taskState === "QUEUED") {
            actionButtons = `
                <button onclick="handleTaskAction(${task.id}, 'pause')" style="cursor:pointer; margin-right: 5px;">⏸️ Pause</button>
                <button onclick="handleTaskAction(${task.id}, 'cancel')" style="cursor:pointer; color:red;">🛑 Cancel</button>
            `;
        } else if (taskState === "PAUSED") {
            actionButtons = `
                <button onclick="handleTaskAction(${task.id}, 'resume')" style="cursor:pointer; margin-right: 5px;">▶️ Resume</button>
                <button onclick="handleTaskAction(${task.id}, 'cancel')" style="cursor:pointer; color:red;">🛑 Cancel</button>
            `;
        }

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
                <!-- Inject the dynamic buttons here -->
                <div class="task-controls" style="margin-top: 10px;">
                    ${actionButtons}
                </div>
            </div>
        `;
    }).join("");
}
