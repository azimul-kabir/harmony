// State tracker to prevent unneeded DOM thrashing
let currentlySyncing = new Set();

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    })[character]);
}

function renderSources(sources) {
    const container = document.getElementById("sources");
    if (!container) return;

    // Destroy skeleton loaders when real data arrives
    container.querySelectorAll('.skeleton-card').forEach(skel => skel.remove());

    if (sources.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 40px; text-align: center; background: var(--bg-surface); border-radius: 16px; border: 1px solid var(--border-color);" class="empty-state">
                <h3>No sources yet</h3>
                <p>Add your first Spotify playlist above to start syncing.</p>
            </div>
        `;
        return;
    }

    // Surgical DOM Patching
    sources.forEach(source => {
        let card = document.getElementById(`source-card-${source.id}`);
        
        // Format Date
        let formattedDate = 'Never';
        if (source.last_synced_at) {
            try {
                // Ensure the string ends in 'Z' to indicate it is a UTC timestamp from the database
                let dateStr = source.last_synced_at;
                if (!dateStr.endsWith("Z") && !dateStr.includes("+")) {
                    dateStr += "Z";
                }
                const dateObj = new Date(dateStr);
                
                // Map saved database settings to native browser locales
                let locale = "en-GB"; // Defaults to DD/MM/YYYY
                if (window.USER_DATE_FORMAT === "MM/DD/YYYY") locale = "en-US";
                else if (window.USER_DATE_FORMAT === "YYYY-MM-DD") locale = "en-CA";
                
                // Strict fallback so Javascript never crashes on an empty or invalid timezone
                let safeTz = window.USER_TIMEZONE;
                if (!safeTz || safeTz === "None" || safeTz.trim() === "") {
                    safeTz = "UTC";
                }
                
                const options = {
                    timeZone: safeTz,
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: window.USER_TIME_FORMAT === "12h"
                };
                
                formattedDate = dateObj.toLocaleString(locale, options);
            } catch (e) {
                // Log the error to console but keep the rest of the page functional
                console.error("Date formatting failed for source:", e);
                formattedDate = "Date Error";
            }
        }

        const lastSync = formattedDate;
        const autoSyncIntervals = [
            [60, "Every hour"],
            [360, "Every 6 hours"],
            [720, "Every 12 hours"],
            [1440, "Daily"],
            [10080, "Weekly"],
        ];
        const autoSyncHtml = `
            <div class="source-auto-sync">
                <div>
                    <strong>Auto-sync</strong>
                    <small>${source.auto_sync_enabled
                        ? `On · every ${source.auto_sync_interval_minutes < 1440
                            ? `${source.auto_sync_interval_minutes / 60} hours`
                            : source.auto_sync_interval_minutes === 1440 ? "day" : "week"}`
                        : "Off · manual sync only"}</small>
                </div>
                <select class="source-auto-sync-interval" data-id="${source.id}" aria-label="Auto-sync interval for ${escapeHtml(source.name)}">
                    ${autoSyncIntervals.map(([value, label]) =>
                        `<option value="${value}"${source.auto_sync_interval_minutes === value ? " selected" : ""}>${label}</option>`
                    ).join("")}
                </select>
                <button class="btn-secondary auto-sync-btn" data-id="${source.id}" data-auto-enabled="${source.auto_sync_enabled}">
                    ${source.auto_sync_enabled ? "Turn off" : "Turn on"}
                </button>
            </div>
        `;
        
        // Evaluate Task State
        let taskHtml = "";
        let isTaskActive = false;
        
        if (source.task) {
            const t = source.task;
            const status = (t.status || "").toUpperCase();
            isTaskActive = ["QUEUED", "RUNNING", "PAUSED"].includes(status);
            
            if (isTaskActive) {
                currentlySyncing.add(source.id);
                const finished = t.completed + t.failed + t.skipped;
                const percent = t.total === 0 ? 0 : (finished / t.total) * 100;
                
                let taskActions = "";
                if (status === "RUNNING" || status === "QUEUED") {
                    taskActions = `
                        <button class="btn-secondary pause-btn" data-task-id="${t.id}">⏸ Pause</button>
                        <button class="btn-secondary cancel-btn" data-task-id="${t.id}" style="color: var(--danger); border-color: var(--danger);">🚫 Cancel</button>
                    `;
                } else if (status === "PAUSED") {
                    taskActions = `
                        <button class="btn-secondary resume-btn" data-task-id="${t.id}">▶ Resume</button>
                        <button class="btn-secondary cancel-btn" data-task-id="${t.id}" style="color: var(--danger); border-color: var(--danger);">🚫 Cancel</button>
                    `;
                }

                taskHtml = `
                    <div class="task-progress-container" style="margin-top: 16px;">
                        <div style="display:flex; justify-content:space-between; font-size:0.85rem; font-weight: 600; color: var(--text-main);">
                            <span>${status === 'RUNNING' ? 'Syncing...' : status}</span>
                            <span>${finished} / ${t.total} Tracks</span>
                        </div>
                        <div class="task-progress-bar">
                            <div class="task-progress-fill" style="width:${percent}%"></div>
                        </div>
                        ${t.current ? `<div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Downloading: ${escapeHtml(t.current)}</div>` : ""}
                        <div style="margin-top: 12px; display:flex; gap: 8px;">
                            ${taskActions}
                        </div>
                    </div>
                `;
            } else {
                currentlySyncing.delete(source.id);
            }
        } else {
            currentlySyncing.delete(source.id);
        }

        // Actions Block
        let actionsHtml = "";
        if (!isTaskActive) {
            actionsHtml = `
                <button class="btn-secondary sync-btn" data-id="${source.id}">Sync now</button>
                <button class="btn-secondary toggle-btn" data-id="${source.id}" data-enabled="${source.enabled}">
                    ${source.enabled ? "Disable" : "Enable"}
                </button>
                <button class="btn-secondary delete-btn" data-id="${source.id}">Delete</button>
            `;
        }

        const playlistHtml = source.playlist ? `
            <div class="source-counts">
                <div><strong>${source.playlist.total}</strong><span>Source</span></div>
                <div><strong>${source.playlist.exported}</strong><span>Available</span></div>
                <div><strong>${Math.max(0, source.playlist.total - source.playlist.exported)}</strong><span>Missing</span></div>
            </div>
        ` : "";
        const outcomeHtml = source.task && !isTaskActive ? `
            <div class="source-outcome">
                <span>${source.task.completed} downloaded</span>
                <span>${source.task.skipped} already owned</span>
                <span class="${source.task.failed ? "has-failures" : ""}">${source.task.failed} failed</span>
            </div>
        ` : "";

        const innerHTML = `
            <div class="source-header">
                <h3>${escapeHtml(source.name)}</h3>
                <span class="badge ${source.enabled ? "badge-completed" : "badge-cancelled"}">
                    ${source.enabled ? "Active" : "Disabled"}
                </span>
            </div>
            <div class="source-meta" style="margin-top: 16px;">
                <div><strong>Type:</strong> ${escapeHtml(source.type)}</div>
                <div><strong>Last Sync:</strong> ${lastSync}</div>
            </div>
            ${autoSyncHtml}
            ${playlistHtml}
            ${outcomeHtml}
            ${taskHtml}
            <div class="source-actions" style="margin-top: 16px; align-items: center;">
                ${actionsHtml}
                <a class="btn-secondary source-open-link" href="${escapeHtml(source.spotify_url)}" target="_blank" rel="noopener">Spotify</a>
            </div>
        `;

        // If card exists, update HTML, otherwise append new card
        if (card) {
            if (card.innerHTML !== innerHTML) {
                card.innerHTML = innerHTML;
            }
        } else {
            card = document.createElement('div');
            card.id = `source-card-${source.id}`;
            card.className = "source-card";
            card.innerHTML = innerHTML;
            container.appendChild(card);
        }
    });

    // Remove deleted sources from the UI
    const incomingIds = sources.map(s => `source-card-${s.id}`);
    Array.from(container.children).forEach(child => {
        if (!incomingIds.includes(child.id) && child.id.startsWith('source-card-')) {
            child.remove();
        }
    });

    if (container.children.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 40px; text-align: center; background: var(--bg-surface); border-radius: 16px; border: 1px solid var(--border-color);" class="empty-state">
                <h3>No sources yet</h3>
                <p>Add your first Spotify playlist above to start syncing.</p>
            </div>
        `;
    }

    bindEvents();
}

function bindEvents() {
    document.querySelectorAll(".sync-btn").forEach(btn => btn.onclick = syncSource);
    document.querySelectorAll(".toggle-btn").forEach(btn => btn.onclick = toggleSource);
    document.querySelectorAll(".delete-btn").forEach(btn => btn.onclick = deleteSource);
    document.querySelectorAll(".auto-sync-btn").forEach(btn => btn.onclick = updateAutoSync);
    document.querySelectorAll(".source-auto-sync-interval").forEach(select => select.onchange = updateAutoSyncInterval);
    
    document.querySelectorAll(".pause-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "pause"));
    document.querySelectorAll(".resume-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "resume"));
    document.querySelectorAll(".cancel-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "cancel"));
}

async function saveAutoSync(sourceId, enabled, interval, control) {
    control.disabled = true;
    const response = await fetch(`/api/sources/${sourceId}/auto-sync`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled, interval_minutes: Number(interval)}),
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        alert(payload.detail || "Auto-sync settings could not be saved.");
        control.disabled = false;
    }
}

function updateAutoSync(event) {
    const button = event.currentTarget;
    const interval = document.querySelector(`.source-auto-sync-interval[data-id="${button.dataset.id}"]`)?.value || 360;
    saveAutoSync(
        button.dataset.id,
        button.dataset.autoEnabled !== "true",
        interval,
        button,
    );
}

function updateAutoSyncInterval(event) {
    const select = event.currentTarget;
    const button = document.querySelector(`.auto-sync-btn[data-id="${select.dataset.id}"]`);
    saveAutoSync(
        select.dataset.id,
        button?.dataset.autoEnabled === "true",
        select.value,
        select,
    );
}

async function handleTaskAction(event, action) {
    const taskId = event.target.dataset.taskId;
    event.target.disabled = true;
    event.target.innerHTML = '<span class="spinner" style="border-top-color:var(--primary); width:10px; height:10px;"></span>...';
    await fetch(`/api/tasks/${taskId}/${action}`, { method: "POST" });
}

async function deleteSource(event) {
    const id = event.target.dataset.id;
    if (!confirm("Are you sure you want to delete this source?")) return;
    const response = await fetch(`/api/sources/${id}`, { method: "DELETE" });
    if (!response.ok) alert("Delete failed.");
}

async function toggleSource(event) {
    const id = event.target.dataset.id;
    const enabled = event.target.dataset.enabled === "true";
    const response = await fetch(`/api/sources/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
    });
    if (!response.ok) alert("Update failed.");
}

async function syncSource(event) {
    const id = event.target.dataset.id;
    event.target.disabled = true;
    event.target.innerHTML = '<span class="spinner" style="border-top-color:var(--primary); width:10px; height:10px;"></span> Initiating...';
    const response = await fetch(`/api/sources/${id}/sync`, { method: "POST" });
    if (!response.ok) {
        alert("Sync failed.");
        event.target.disabled = false;
        event.target.textContent = "↻ Sync Now";
    }
}

async function addSource(event) {
    event.preventDefault();
    const input = document.getElementById("source-url");
    const submitBtn = event.target.querySelector('button[type="submit"]');
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner" style="border-top-color:#fff;"></span> Adding...';
    
    try {
        const response = await fetch("/api/sources", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ spotify_url: input.value }),
        });
        
        if (!response.ok) throw new Error("Unable to add source.");
        input.value = "";
    } catch (error) {
        alert(error.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "+ Add Source";
    }
}

const addForm = document.getElementById("add-source-form");
if (addForm) {
    addForm.addEventListener("submit", addSource);
}

function connectSourcesSSE() {
    if (!document.getElementById("sources")) return;
    const eventSource = new EventSource("/api/sources/stream");
    
    eventSource.onmessage = function(event) {
        const sources = JSON.parse(event.data);
        renderSources(sources);
    };
    
    eventSource.onerror = function(error) {
        console.error("SSE connection error, attempting to reconnect...", error);
    };
}

connectSourcesSSE();
