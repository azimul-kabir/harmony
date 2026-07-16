document.addEventListener("DOMContentLoaded", () => {
    // Quick Actions: Sync All
    const btnSyncAll = document.getElementById("btn-sync-all");
    if (btnSyncAll) {
        btnSyncAll.addEventListener("click", async (e) => {
            e.target.disabled = true;
            e.target.innerHTML = '<span class="spinner" style="border-top-color: white;"></span> Syncing...';
            try {
                await fetch("/api/sync", { method: "POST" });
            } catch (error) {
                console.error("Failed to sync sources:", error);
            } finally {
                setTimeout(() => {
                    e.target.disabled = false;
                    e.target.textContent = "↻ Sync All Sources";
                }, 2000);
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
            case "COMPLETED": icon = "✓"; label = "Downloaded"; break;
            case "FAILED": icon = "✕"; label = "Failed"; break;
            case "RUNNING": icon = "⬇"; label = "Downloading"; break;
            case "QUEUED": icon = "⏳"; label = "Queued"; break;
            case "SKIPPED": icon = "⏭"; label = "Skipped"; break;
            case "PAUSED": icon = "⏸"; label = "Paused"; break;
            case "CANCELLED": icon = "🚫"; label = "Cancelled"; break;
        }

        return `
            <div class="activity-item">
                <div class="activity-badge">${icon} ${label}</div>
                <div class="activity-title" title="${job.title ?? "Unknown"}">${job.title ?? "Unknown Title"}</div>
                <div class="activity-artist" title="${job.artist ?? "Unknown"}">${job.artist ?? "Unknown Artist"}</div>
            </div>
        `;
    }).join("");
}

function taskStatus(status) {
    switch ((status ?? "").toUpperCase()) {
        case "RUNNING": return "⬇ Downloading";
        case "QUEUED": return "⏳ Queued";
        case "COMPLETED": return "✓ Completed";
        case "FAILED": return "✕ Failed";
        case "PAUSED": return "⏸ Paused";
        case "CANCELLED": return "🚫 Cancelled";
        default: return status;
    }
}

async function handleTaskAction(taskId, action) {
    await fetch(`/api/tasks/${taskId}/${action}`, { method: "POST" });
}

function renderTasks(tasks) {
    const container = document.getElementById("active-tasks");
    if (!container) return;

    if (tasks && tasks.length > 0) {
        const emptyMsg = container.querySelector(".empty-state");
        if (emptyMsg) emptyMsg.remove();
    }

    const newTaskIds = (tasks || []).map(t => String(t.id));
    const existingItems = container.querySelectorAll(".task-item");

    existingItems.forEach(el => {
        const id = el.dataset.taskId;
        if (!newTaskIds.includes(id)) {
            if (!el.classList.contains("fading-out")) {
                el.classList.add("fading-out");
                const statusEl = el.querySelector(".task-status");
                if (statusEl) statusEl.textContent = "✓ Finished";
                const fillEl = el.querySelector(".task-progress-fill");
                if (fillEl) fillEl.style.width = "100%";
                const controls = el.querySelector(".task-controls");
                if (controls) controls.remove();

                setTimeout(() => {
                    el.remove();
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

    tasks.forEach(task => {
        const finished = task.completed + task.failed + task.skipped;
        const percent = task.total === 0 ? 0 : (finished / task.total) * 100;
        const taskState = (task.status ?? "").toUpperCase();

        let actionButtons = "";
        if (taskState === "RUNNING" || taskState === "QUEUED") {
            actionButtons = `
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'pause')">⏸ Pause</button>
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'cancel')" style="color:var(--danger); border-color:var(--danger);">🚫 Cancel</button>
            `;
        } else if (taskState === "PAUSED") {
            actionButtons = `
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'resume')">▶ Resume</button>
                <button class="btn-secondary" onclick="handleTaskAction(${task.id}, 'cancel')" style="color:var(--danger); border-color:var(--danger);">🚫 Cancel</button>
            `;
        }

        let el = container.querySelector(`.task-item[data-task-id="${task.id}"]`);
        
        if (el) {
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
                    newCurrent.style = "font-size:0.85rem; color:var(--text-muted); margin-top:8px;";
                    el.insertBefore(newCurrent, el.querySelector(".task-controls"));
                }
            } else if (currentEl) {
                currentEl.remove();
            }
            el.querySelector(".task-controls").innerHTML = actionButtons;
        } else {
            const wrapper = document.createElement("div");
            wrapper.className = "task-item";
            wrapper.dataset.taskId = task.id;
            wrapper.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div class="task-title" style="font-weight:600; font-size:1.1rem; margin-bottom:8px;">🎵 ${task.name}</div>
                    <div class="task-status" style="font-size:0.9rem; color:var(--text-muted);">${taskStatus(task.status)}</div>
                </div>
                <div class="task-progress-container" style="padding: 0; background: transparent; border: none;">
                    <div class="task-progress-bar">
                        <div class="task-progress-fill" style="width:${percent}%"></div>
                    </div>
                </div>
                <div class="task-progress" style="font-size:0.85rem; color:var(--text-muted); margin-top:4px; text-align:right;">${finished} / ${task.total}</div>
                ${task.current ? `<div class="task-current" style="font-size:0.85rem; color:var(--text-muted); margin-top:8px;">Now downloading: ${task.current}</div>` : ""}
                <div class="task-controls" style="margin-top: 16px; display: flex; gap: 8px;">${actionButtons}</div>
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
}
