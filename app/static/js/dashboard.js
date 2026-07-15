function renderStats(stats) {
    if (!stats) return;
    
    document.getElementById("songs-count").textContent = stats.songs;
    document.getElementById("downloads-count").textContent = stats.downloads;
    document.getElementById("sources-count").textContent = stats.sources;
    document.getElementById("failed-count").textContent = stats.failed;
}

function renderActivity(jobs) {
    const container = document.getElementById("recent-activity");
    if (!container) return;

    if (!jobs || jobs.length === 0) {
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

async function handleTaskAction(taskId, action) {
    // Send the command to the API
    await fetch(`/api/tasks/${taskId}/${action}`, {
        method: "POST"
    });
    // We no longer manually refresh the UI here because the 
    // SSE stream will push the new state in the next tick.
}

function renderTasks(tasks) {
    const container = document.getElementById("active-tasks");
    if (!container) return;

    if (!tasks || tasks.length === 0) {
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

function connectSSE() {
    // Only connect if we are actually on the dashboard page
    if (!document.getElementById("songs-count")) {
        return;
    }

    // Establish the SSE connection
    const eventSource = new EventSource("/api/dashboard/stream");

    // Listen for incoming messages from the server
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        // Push the new data to the DOM
        renderStats(data.stats);
        renderActivity(data.activity);
        renderTasks(data.tasks);
    };

    // Handle connection drops and let the browser auto-reconnect
    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

// Initialize the stream on page load
connectSSE();
