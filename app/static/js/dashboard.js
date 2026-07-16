document.addEventListener("DOMContentLoaded", () => {
    // Quick Actions: Sync All
    const btnSyncAll = document.getElementById("btn-sync-all");
    if (btnSyncAll) {
        btnSyncAll.addEventListener("click", async (e) => {
            e.target.disabled = true;
            e.target.innerHTML = '<span class="spinner"></span> Syncing...';
            try {
                await fetch("/api/sync", { method: "POST" });
            } catch (error) {
                console.error("Failed to sync sources:", error);
            } finally {
                setTimeout(() => {
                    e.target.disabled = false;
                    e.target.textContent = "Sync All Sources";
                }, 2000); // Keep success state briefly
            }
        });
    }

    connectSSE();
});

function renderStats(stats) {
    if (!stats) return;
    document.getElementById("card-songs").textContent = stats.songs;
    document.getElementById("card-downloads").textContent = stats.downloads;
    document.getElementById("card-sources").textContent = stats.sources;
    document.getElementById("card-failed").textContent = stats.failed;
}

function renderActivity(jobs) {
    const container = document.getElementById("recent-activity");
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = "<p class='empty-state'>No recent activity.</p>";
        return;
    }

    container.innerHTML = jobs.map(job => {
        const status = (job.status ?? "").toUpperCase();
        let icon = "⏳";
        let label = status;

        switch (status) {
            case "COMPLETED":
                icon = "✓";
                label = "Downloaded";
                break;
            case "FAILED":
                icon = "✕";
                label = "Failed";
                break;
            case "RUNNING":
                icon = "⬇";
                label = "Downloading";
                break;
            case "QUEUED":
                icon = "⏳";
                label = "Queued";
                break;
            case "SKIPPED":
                icon = "⏭";
                label = "Skipped";
                break;
            case "PAUSED":
                icon = "⏸";
                label = "Paused";
                break;
            case "CANCELLED":
                icon = "🚫";
                label = "Cancelled";
                break;
        }

        return `
            <div class="activity-item">
                <div class="activity-header">
                    <span class="activity-icon">${icon}</span>
                    <span class="activity-status">${label}</span>
                </div>
                <div class="activity-title" title="${job.title ?? "Unknown Title"}">
                    ${job.title ?? "Unknown Title"}
                </div>
                <div class="activity-artist" title="${job.artist ?? "Unknown Artist"}">
                    ${job.artist ?? "Unknown Artist"}
                </div>
            </div>
        `;
    }).join("");
}

function taskStatus(status) {
    switch ((status ?? "").toUpperCase()) {
        case "RUNNING":
            return "⬇ Downloading";
        case "QUEUED":
            return "⏳ Queued";
        case "COMPLETED":
            return "✓ Completed";
        case "FAILED":
            return "✕ Failed";
        case "PAUSED":
            return "⏸ Paused";
        case "CANCELLED":
            return "🚫 Cancelled";
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
        const emptyMsg = container.querySelector(".empty-state");
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
                if (statusEl) statusEl.textContent = "✓ Finished";
                
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
                        container.innerHTML = "<p class='empty-state'>No active tasks.</p>";
                    }
                }, 3000);
            }
        }
    });

    if (!tasks || tasks.length === 0) {
        if (container.children.length === 0) {
            container.innerHTML = "<p class='empty-state'>No active tasks.</p>";
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
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'pause')" style="cursor:pointer; margin-right: 5px;">⏸ Pause</button>
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'cancel')" style="cursor:pointer; color:#dc3545;">🚫 Cancel</button>
            `;
        } else if (taskState === "PAUSED") {
            actionButtons = `
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'resume')" style="cursor:pointer; margin-right: 5px;">▶ Resume</button>
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'cancel')" style="cursor:pointer; color:#dc3545;">🚫 Cancel</button>
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
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div class="task-title" style="font-weight:600; font-size:1.1rem; margin-bottom:8px;">🎵 ${task.name}</div>
                    <div class="task-status" style="font-size:0.9rem; color:#555;">${taskStatus(task.status)}</div>
                </div>
                <div class="task-progress-container" style="padding: 0; background: transparent; border: none;">
                    <div class="task-progress-bar">
                        <div class="task-progress-fill" style="width:${percent}%"></div>
                    </div>
                </div>
                <div class="task-progress" style="font-size:0.85rem; color:#666; margin-top:4px; text-align:right;">${finished} / ${task.total}</div>
                ${task.current ? `<div class="task-current" style="font-size:0.85rem; color:#666; margin-top:8px;">Now downloading: ${task.current}</div>` : ""}
                <div class="task-controls" style="margin-top: 12px;">${actionButtons}</div>
            `;
            container.appendChild(wrapper);
        }
    });
}

function connectSSE() {
    if (!document.getElementById("card-songs")) return;
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
