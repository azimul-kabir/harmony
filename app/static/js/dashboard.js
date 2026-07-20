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
    document.getElementById("card-artists").textContent = stats.artists;
    document.getElementById("card-albums").textContent = stats.albums;
    document.getElementById("card-storage").textContent = `${stats.storage.used_gb} GB`;

    // Update Storage Bar
    const labels = document.getElementById("storage-labels");
    const bar = document.getElementById("storage-bar");
    if(labels && bar) {
        labels.textContent = `${stats.storage.used_gb} GB / ${stats.storage.total_gb} GB`;
        const pct = stats.storage.total_gb ? (stats.storage.used_gb / stats.storage.total_gb) * 100 : 0;
        bar.style.width = `${pct}%`;
    }
}

function renderNavidromeHealth(nd) {
    if(!nd) return;

    const badge = document.getElementById("nd-health-badge");
    const details = document.getElementById("nd-health-details");
    const syncStatus = document.getElementById("nd-sync-status");
    const btnRescan = document.getElementById("btn-manual-rescan");

    if(!badge || !details || !syncStatus) return;

    if(!nd.connected) {
        badge.style.background = "var(--text-muted)";
        details.textContent = "Not configured";
        syncStatus.textContent = "Offline";
        syncStatus.style.color = "var(--text-muted)";
        btnRescan.style.display = 'none';
        return;
    }

    if(nd.online) {
        badge.style.background = "var(--success)";
        details.innerHTML = `Online • ${nd.latency}ms latency<br>${nd.is_scanning ? '<span style="color:var(--primary);">Scanning...</span>' : 'Idle'}`;

        if (nd.delta > 0) {
            syncStatus.textContent = `${nd.delta} Missing Tracks`;
            syncStatus.style.color = "var(--warning, #eab308)";
            btnRescan.style.display = 'inline-block';
        } else {
            syncStatus.textContent = "✓ Synced";
            syncStatus.style.color = "var(--success)";
            btnRescan.style.display = 'none';
        }
    } else {
        badge.style.background = "var(--error)";
        details.textContent = "Offline or unreachable";
        syncStatus.textContent = "Disconnected";
        syncStatus.style.color = "var(--error)";
        btnRescan.style.display = 'none';
    }

    btnRescan.onclick = async () => {
        btnRescan.disabled = true;
        btnRescan.textContent = "Scanning...";
        try {
            await fetch('/api/navidrome/scan', { method: 'POST' });
        } finally {
            setTimeout(() => {
                btnRescan.disabled = false;
                btnRescan.textContent = "Force Rescan";
            }, 2000);
        }
    }
}

// Inside app/static/js/dashboard.js, update renderWorkers() and renderActivity():

function renderWorkers(workers, maxWorkers) {
    const container = document.getElementById("workers-grid");
    const badge = document.getElementById("worker-count-badge");
    if (!container) return;

    badge.textContent = `${workers.length} / ${maxWorkers} Active`;
    
    if (workers.length > 0) {
        badge.classList.remove("badge-queued");
        badge.classList.add("badge-running");
    } else {
        badge.classList.remove("badge-running");
        badge.classList.add("badge-queued");
    }

    let html = "";
    for (let i = 0; i < maxWorkers; i++) {
        if (i < workers.length) {
            const worker = workers[i];
            
            // NEW: Artwork HTML Generation
            const coverImg = worker.cover_url
                ? `<img src="${worker.cover_url}" alt="Cover" style="width: 48px; height: 48px; border-radius: 6px; object-fit: cover; flex-shrink: 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">`
                : `<div style="width: 48px; height: 48px; border-radius: 6px; background: var(--bg-surface-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid var(--border-color);"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

            html += `
                <div class="worker-card">
                    <div class="worker-header" style="margin-bottom: 12px;">
                        <span>Thread ${i + 1}</span>
                        <span class="worker-status active"><span class="spinner" style="width:10px;height:10px;border-width:2px;margin:0;"></span></span>
                    </div>
                    <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 8px;">
                        ${coverImg}
                        <div style="min-width: 0;">
                            <div class="worker-track" title="${worker.title ?? "Unknown"}">${worker.title ?? "Unknown Title"}</div>
                            <div class="worker-artist" title="${worker.artist ?? "Unknown"}">${worker.artist ?? "Unknown Artist"}</div>
                        </div>
                    </div>
                    <div class="task-progress-bar" style="margin-top:auto;">
                        <div class="task-progress-fill worker-pulse"></div>
                    </div>
                </div>
            `;
        } else {
            html += `
                <div class="worker-card idle">
                    <div class="worker-header">
                        <span>Thread ${i + 1}</span>
                        <span class="worker-status">Waiting</span>
                    </div>
                    <div class="worker-track" style="color: var(--text-muted);">Idle</div>
                    <div class="worker-artist">-</div>
                </div>
            `;
        }
    }
    container.innerHTML = html;
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
        let icon = " ";
        let label = status;

        switch (status) {
            case "COMPLETED": icon = " "; label = "Downloaded"; break;
            case "FAILED": icon = " "; label = "Failed"; break;
            case "RUNNING": icon = " "; label = "Downloading"; break;
            case "QUEUED": icon = " "; label = "Queued"; break;
            case "SKIPPED": icon = " "; label = "Skipped"; break;
            case "PAUSED": icon = " "; label = "Paused"; break;
            case "CANCELLED": icon = " "; label = "Cancelled"; break;
        }

        // NEW: Artwork HTML Generation
        const coverImg = job.cover_url
            ? `<img src="${job.cover_url}" alt="Cover" style="width: 36px; height: 36px; border-radius: 6px; object-fit: cover; flex-shrink: 0; margin-right: 12px;">`
            : `<div style="width: 36px; height: 36px; border-radius: 6px; background: var(--bg-surface-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-right: 12px; color: var(--text-muted); border: 1px solid var(--border-color);"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`;

        return `
            <div class="activity-item">
                <div class="activity-badge">${icon} ${label}</div>
                <div style="display: flex; align-items: center; min-width: 0;">
                    ${coverImg}
                    <div class="activity-title" title="${job.title ?? "Unknown"}">${job.title ?? "Unknown Title"}</div>
                </div>
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
                        container.innerHTML = "<p class='empty-state'>No active queue tasks.</p>";
                    }
                }, 3000);
            }
        }
    });

    if (!tasks || tasks.length === 0) {
        if (container.children.length === 0) {
            container.innerHTML = "<p class='empty-state'>No active queue tasks.</p>";
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
                    currentEl.textContent = `Processing: ${task.current}`;
                } else {
                    const newCurrent = document.createElement("div");
                    newCurrent.className = "task-current";
                    newCurrent.textContent = `Processing: ${task.current}`;
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
                ${task.current ? `<div class="task-current" style="font-size:0.85rem; color:var(--text-muted); margin-top:8px;">Processing: ${task.current}</div>` : ""}
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
        renderNavidromeHealth(data.navidrome);
        renderWorkers(data.workers || [], data.max_workers || 4); // NEW: Render workers
        renderActivity(data.activity);
        renderTasks(data.tasks);
    };
}
