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

    // Server-rendered attention cards are actionable before the first SSE
    // event arrives. Subsequent patches replace this handler per card.
    document.querySelectorAll("[data-attention-recovery]").forEach((button) => {
        const action = button.dataset.attentionRecovery;
        if (action) button.onclick = () => runAttentionRecovery(action, button);
    });

    connectSSE();
});

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / (1024 ** index)).toFixed(index < 3 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(seconds) {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(totalSeconds / 60);
    return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

function formatQueueDuration(seconds) {
    return seconds === null || seconds === undefined ? "—" : formatDuration(seconds);
}

function renderDownloadTrends(trends) {
    setText("trend-completed", Number(trends.completed || 0).toLocaleString());
    setText("trend-failed", Number(trends.failed || 0).toLocaleString());
    setText("trend-cancelled", Number(trends.cancelled || 0).toLocaleString());
    setText("trend-success-rate", `${Math.round(Number(trends.success_rate || 0) * 100)}%`);
    const chart = document.getElementById("download-trend-chart");
    if (!chart) return;
    const daily = Array.isArray(trends.daily) ? trends.daily.slice(-7) : [];
    const maximum = Math.max(1, ...daily.map((day) => Number(day.completed || 0)));
    const existing = new Map(Array.from(chart.children).map((bar) => [bar.dataset.date, bar]));
    daily.forEach((day) => {
        let bar = existing.get(day.date);
        if (!bar) {
            bar = document.createElement("div"); bar.className = "download-trend-bar"; bar.dataset.date = day.date;
            const value = document.createElement("span"); value.className = "download-trend-value";
            const column = document.createElement("div"); column.className = "download-trend-column";
            const label = document.createElement("span"); label.className = "download-trend-label";
            bar.append(value, column, label);
        }
        const completed = Number(day.completed || 0), failed = Number(day.failed || 0), cancelled = Number(day.cancelled || 0);
        const [value, column, label] = bar.children;
        value.textContent = completed.toLocaleString();
        column.style.height = `${Math.max(completed ? 10 : 2, Math.round(completed / maximum * 100))}%`;
        column.classList.toggle("has-attention", failed + cancelled > 0);
        bar.title = `${day.date}: ${completed} completed, ${failed} failed, ${cancelled} cancelled`;
        label.textContent = day.date.slice(5);
        chart.appendChild(bar); existing.delete(day.date);
    });
    existing.forEach((bar) => bar.remove());
}

function renderQueueHealth(health) {
    const workers = Number(health.active_workers || 0), configured = Number(health.configured_workers || 0);
    setText("queue-utilization", health.utilization === null || health.utilization === undefined ? "—" : `${workers}/${configured} (${Math.round(Number(health.utilization) * 100)}%)`);
    setText("health-queued-jobs", Number(health.queued_jobs || 0).toLocaleString());
    setText("health-running-jobs", Number(health.running_jobs || 0).toLocaleString());
    setText("health-paused-jobs", Number(health.paused_jobs || 0).toLocaleString());
    setText("queue-oldest", formatQueueDuration(health.oldest_queue_seconds));
    setText("queue-longest-running", formatQueueDuration(health.longest_running_seconds));
    setText("queue-average-wait", formatQueueDuration(health.average_queue_wait_seconds));
    const stalled = document.getElementById("queue-stalled");
    if (stalled) { stalled.textContent = health.stalled ? "Stalled" : "Healthy"; stalled.classList.toggle("is-stalled", Boolean(health.stalled)); }
}

function renderAlbumInsight(id, album, detail) {
    const element = document.getElementById(id);
    if (!element) return;
    const title = element.querySelector("strong");
    const subtitle = element.querySelector("small");
    if (!album) {
        element.href = "/library";
        title.textContent = "No album data";
        subtitle.textContent = "—";
        return;
    }
    element.href = `/library?album=${encodeURIComponent(album.name)}`;
    title.textContent = album.name;
    subtitle.textContent = detail(album);
}

function renderDashboard(snapshot) {
    if (!snapshot) return;
    const kpis = snapshot.kpis || {};
    setText("kpi-songs", Number(kpis.songs || 0).toLocaleString());
    setText("kpi-albums", Number(kpis.albums || 0).toLocaleString());
    setText("kpi-artists", Number(kpis.artists || 0).toLocaleString());
    setText("kpi-sources", Number(kpis.sources || 0).toLocaleString());
    setText("kpi-playlists", Number(kpis.playlists || 0).toLocaleString());
    setText("kpi-storage", formatBytes(kpis.storage_bytes));
    setText("kpi-health", `${Number(kpis.health_score || 0)}%`);
    setText("kpi-failed", Number(kpis.failed_jobs || 0).toLocaleString());
    renderAttention(snapshot.attention || {});

    const downloads = snapshot.downloads || {};
    setText("queue-running", Number(downloads.running || 0).toLocaleString());
    setText("queue-queued", Number(downloads.queued || 0).toLocaleString());
    setText("queue-today", Number(downloads.completed_today || 0).toLocaleString());
    setText("queue-failed", Number(downloads.failed || 0).toLocaleString());
    renderDownloadTrends(snapshot.download_trends || {});
    renderQueueHealth(snapshot.queue_health || {});

    const health = snapshot.health || {};
    setText("health-score", `${Number(health.score || 0)}%`);
    setText("health-artwork", Number(health.missing_artwork || 0).toLocaleString());
    setText("health-metadata", Number(health.missing_metadata || 0).toLocaleString());
    setText("health-files", Number(health.missing_files || 0).toLocaleString());
    setText("health-suggestions", Number(health.pending_suggestions || 0).toLocaleString());
    const artworkLink = document.getElementById("health-artwork-link");
    if (artworkLink) artworkLink.href = "/library?missing_artwork=true";
    const analytics = snapshot.analytics || {};
    setText("insight-recently-added", Number(analytics.recently_added || 0).toLocaleString());
    setText("insight-genres", Number(analytics.genres || 0).toLocaleString());
    setText("insight-bitrate", analytics.average_bitrate ? `${Math.round(analytics.average_bitrate / 1000)} kbps` : "—");
    setText("insight-duration", analytics.average_duration ? formatDuration(analytics.average_duration) : "—");
    renderAlbumInsight("insight-largest-album", analytics.largest_album, (album) => `${Number(album.song_count || 0).toLocaleString()} songs`);
    renderAlbumInsight("insight-newest-album", analytics.newest_album, (album) => `${album.artist || "Unknown Artist"} · ${album.year || "Unknown year"}`);
    renderAlbumInsight("insight-oldest-album", analytics.oldest_album, (album) => `${album.artist || "Unknown Artist"} · ${album.year || "Unknown year"}`);
    renderMaintenance(snapshot.maintenance || []);
    renderCollections(snapshot.collections || []);
}

function renderAttention(attention) {
    const container = document.getElementById("dashboard-attention-list");
    const empty = document.getElementById("dashboard-attention-empty");
    if (!container || !empty) return;

    const items = Array.isArray(attention.items) ? attention.items : [];
    const total = Number(attention.total_count || 0);
    // The server owns the state decision; do not independently infer healthy
    // from a partially received stream payload.
    const healthy = attention.healthy === true;
    setText("attention-total", `${total.toLocaleString()} ${total === 1 ? "issue" : "issues"}`);
    setText("dashboard-attention-headline", attention.headline || (healthy ? "Everything looks healthy" : "Items need attention"));
    setText("dashboard-attention-message", attention.message || "");
    empty.hidden = !healthy;

    const existing = new Map(
        Array.from(container.children).map((element) => [element.dataset.attentionKey, element])
    );
    items.forEach((issue) => {
        let row = existing.get(issue.key);
        if (!row) {
            row = document.createElement("article");
            row.dataset.attentionKey = issue.key;
            const severity = document.createElement("span");
            severity.className = "dashboard-attention-severity";
            const content = document.createElement("div");
            content.className = "dashboard-attention-content";
            const title = document.createElement("strong");
            const description = document.createElement("span");
            description.className = "dashboard-attention-description";
            content.append(title, description);
            const count = document.createElement("strong");
            count.className = "dashboard-attention-count";
            const link = document.createElement("a");
            link.className = "btn-secondary dashboard-attention-action";
            const recovery = document.createElement("button");
            recovery.className = "btn-secondary dashboard-attention-recovery";
            recovery.type = "button";
            const controls = document.createElement("div");
            controls.className = "dashboard-attention-controls";
            controls.append(link, recovery);
            row.append(severity, content, count, controls);
        }
        row.className = `dashboard-attention-item severity-${issue.severity}`;
        const [severity, content, count, controls] = row.children;
        const [link, recovery] = controls.children;
        severity.textContent = issue.severity;
        content.querySelector("strong").textContent = issue.title;
        content.querySelector("span").textContent = issue.description;
        count.textContent = Number(issue.count || 0).toLocaleString();
        link.href = issue.href;
        link.textContent = issue.action_label;
        link.setAttribute("aria-label", `${issue.action_label} ${issue.title}`);
        recovery.hidden = !issue.recovery_action;
        if (issue.recovery_action) {
            recovery.textContent = issue.recovery_label;
            recovery.setAttribute("aria-label", `${issue.recovery_label} for ${issue.title}`);
            recovery.dataset.attentionRecovery = issue.recovery_action;
            recovery.onclick = () => runAttentionRecovery(issue.recovery_action, recovery);
        } else {
            recovery.dataset.attentionRecovery = "";
            recovery.onclick = null;
        }
        container.appendChild(row);
        existing.delete(issue.key);
    });
    existing.forEach((row) => row.remove());
}

const ATTENTION_RECOVERY_ENDPOINTS = {
    verify_files: "/api/library/health/actions/verify",
    analyze_metadata: "/api/library/health/metadata/analyze",
    refresh_library: "/api/library/health/actions/refresh",
};

async function runAttentionRecovery(action, button) {
    const endpoint = ATTENTION_RECOVERY_ENDPOINTS[action];
    if (!endpoint || button.disabled) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Queued";
    try {
        const response = await fetch(endpoint, { method: "POST" });
        if (!response.ok) throw new Error("Unable to queue recovery action.");
    } catch (error) {
        button.textContent = "Try again";
        button.disabled = false;
        console.error("Dashboard recovery action failed:", error);
        return;
    }
    setTimeout(() => {
        button.disabled = false;
        button.textContent = originalLabel;
    }, 1500);
}

function renderMaintenance(jobs) {
    const container = document.getElementById("dashboard-maintenance-list");
    if (!container) return;
    container.replaceChildren();
    if (!jobs.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "No completed maintenance jobs yet.";
        container.appendChild(empty);
        return;
    }
    jobs.forEach((job) => {
        const item = document.createElement("article");
        item.className = `dashboard-maintenance-item status-${String(job.status || "").toLowerCase()}`;
        const name = document.createElement("strong");
        name.textContent = job.name || "Library maintenance";
        const detail = document.createElement("small");
        const processed = Number(job.completed || 0) + Number(job.failed || 0) + Number(job.skipped || 0);
        detail.textContent = `${String(job.status || "unknown").replaceAll("_", " ")} · ${processed}/${Number(job.total || 0)}${job.error_code ? ` · ${job.error_code}` : ""}`;
        item.append(name, detail);
        container.appendChild(item);
    });
}

function renderCollections(collections) {
    const container = document.getElementById("dashboard-collections");
    if (!container) return;
    container.replaceChildren();
    collections.forEach((collection) => {
        const link = document.createElement("a");
        link.href = `/library?collection=${encodeURIComponent(collection.id)}`;
        const name = document.createElement("span");
        name.textContent = collection.name;
        const count = document.createElement("strong");
        count.textContent = Number(collection.song_count || 0).toLocaleString();
        link.append(name, count);
        container.appendChild(link);
    });
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

function activityDetails(status) {
    const normalized = String(status || "unknown").toLowerCase();
    const labels = {
        completed: "Downloaded",
        failed: "Failed",
        running: "Downloading",
        queued: "Queued",
        skipped: "Skipped",
        paused: "Paused",
        cancelled: "Cancelled",
    };
    return { status: normalized, label: labels[normalized] || "Updated" };
}

function formatActivityTime(value) {
    if (!value) return "Recently";
    const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
    if (Number.isNaN(date.getTime())) return "Recently";
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return "Just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function renderActivity(jobs) {
    const container = document.getElementById("recent-activity");
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "No recent download activity.";
        container.replaceChildren(empty);
        return;
    }

    const existing = new Map(
        Array.from(container.querySelectorAll("[data-activity-id]")).map((row) => [row.dataset.activityId, row])
    );
    jobs.forEach((job) => {
        const key = String(job.id);
        let row = existing.get(key);
        if (!row) {
            row = document.createElement("a");
            row.dataset.activityId = key;
            const marker = document.createElement("span");
            marker.className = "activity-marker";
            const content = document.createElement("div");
            content.className = "activity-content";
            const title = document.createElement("strong");
            const artist = document.createElement("span");
            artist.className = "activity-artist";
            content.append(title, artist);
            const meta = document.createElement("div");
            meta.className = "activity-meta";
            const status = document.createElement("span");
            const time = document.createElement("time");
            meta.append(status, time);
            row.append(marker, content, meta);
        }
        const details = activityDetails(job.status);
        row.className = `activity-item activity-${details.status}`;
        row.href = ["failed", "cancelled"].includes(details.status) ? "/downloads?status=failed" : "/downloads";
        const [marker, content, meta] = row.children;
        marker.setAttribute("aria-hidden", "true");
        content.querySelector("strong").textContent = job.title || "Unknown title";
        content.querySelector("span").textContent = job.artist || "Unknown artist";
        meta.querySelector("span").textContent = details.label;
        const time = meta.querySelector("time");
        time.dateTime = job.event_at || "";
        time.textContent = formatActivityTime(job.event_at);
        row.setAttribute("aria-label", `${details.label}: ${job.title || "Unknown title"}`);
        container.appendChild(row);
        existing.delete(key);
    });
    existing.forEach((row) => row.remove());
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
    if (!document.getElementById("kpi-songs")) return;
    const eventSource = new EventSource("/api/dashboard/stream");
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        renderDashboard(data);
        renderWorkers(data.workers || [], data.max_workers || 4); // NEW: Render workers
        renderActivity(data.activity);
        renderTasks(data.tasks);
    };
}
