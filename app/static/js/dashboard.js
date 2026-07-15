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
    await fetch(`/api/tasks/${taskId}/${action}`, {
        method: "POST"
    });
}

function renderTasks(tasks) {
    const container = document.getElementById("active-tasks");
    if (!container) return;

    // Clear the "No active tasks" message if we are about to inject tasks
    if (tasks && tasks.length > 0) {
        const emptyMsg = container.querySelector("p");
        if (emptyMsg) emptyMsg.remove();
    }

    const newTaskIds = (tasks || []).map(t => String(t.id));
    const existingItems = container.querySelectorAll(".task-item");

    // 1. Check for tasks that have finished (no longer pushed by the server)
    existingItems.forEach(el => {
        const id = el.dataset.taskId;
        if (!newTaskIds.includes(id)) {
            // Task has dropped from the queue. Fade it out!
            if (!el.classList.contains("fading-out")) {
                el.classList.add("fading-out");
                
                // Visually force a 100% completion state during the fade out
                const statusEl = el.querySelector(".task-status");
                if (statusEl) statusEl.textContent = "✅ Finished";
                
                const fillEl = el.querySelector(".task-progress-fill");
                if (fillEl) fillEl.style.width = "100%";
                
                // Hide the pause/cancel controls immediately
                const controls = el.querySelector(".task-controls");
                if (controls) controls.remove();

                // Remove the element from the DOM after the 3-second CSS animation ends
                setTimeout(() => {
                    el.remove();
                    // If this was the last task, restore the empty message
                    if (container.children.length === 0) {
                        container.innerHTML = "<p>No active tasks.</p>";
                    }
                }, 3000);
            }
        }
    });

    if (!tasks || tasks.length === 0) {
        if (container.children.length === 0) {
            container.innerHTML = "<p>No active tasks.</p>";
        }
        return;
    }

    // 2. Surgically update existing tasks or create new ones
    tasks.forEach(task => {
        const finished = task.completed + task.failed + task.skipped;
        const percent = task.total === 0 ? 0 : (finished / task.total) * 100;
        const taskState = (task.status ?? "").toUpperCase();

        let actionButtons = "";
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

        let el = container.querySelector(`.task-item[data-task-id="${task.id}"]`);
        
        if (el) {
            // Update the specific elements to maintain buttery-smooth CSS width transitions
            el.querySelector(".task-status").textContent = taskStatus(task.status);
            el.querySelector(".task-progress-fill").style.width = `${percent}%`;
            el.querySelector(".task-progress").textContent = `${finished} / ${task.total}`;
            
            const currentEl = el.querySelector(".task-current");
            if (task.current) {
                if (currentEl) {
                    currentEl.textContent = `Now downloading: ${task.current}`;
                } else {
                    const newCurrent = document.createElement("div");
                    newCurrent.className = "task-current";
                    newCurrent.textContent = `Now downloading: ${task.current}`;
                    el.insertBefore(newCurrent, el.querySelector(".task-controls"));
                }
            } else if (currentEl) {
                currentEl.remove();
            }

            el.querySelector(".task-controls").innerHTML = actionButtons;
        } else {
            // Insert a brand new task
            const wrapper = document.createElement("div");
            wrapper.className = "task-item";
            wrapper.dataset.taskId = task.id;
            wrapper.innerHTML = `
                <div class="task-title">🎵 ${task.name}</div>
                <div class="task-status">${taskStatus(task.status)}</div>
                <div class="task-progress-bar">
                    <div class="task-progress-fill" style="width:${percent}%"></div>
                </div>
                <div class="task-progress">${finished} / ${task.total}</div>
                ${task.current ? `<div class="task-current">Now downloading: ${task.current}</div>` : ""}
                <div class="task-controls" style="margin-top: 10px;">${actionButtons}</div>
            `;
            container.appendChild(wrapper);
        }
    });
}

function connectSSE() {
    if (!document.getElementById("songs-count")) return;

    const eventSource = new EventSource("/api/dashboard/stream");

    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        renderStats(data.stats);
        renderActivity(data.activity);
        renderTasks(data.tasks);
    };

    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

connectSSE();
