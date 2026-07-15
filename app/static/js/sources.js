// State tracker to prevent unneeded DOM thrashing
let currentlySyncing = new Set();

function renderSources(sources) {
    const container = document.getElementById("sources");
    if (!container) return;

    if (sources.length === 0) {
        container.innerHTML = `
            <div class="panel empty-state">
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
        let lastSync = "Never";
        if (source.last_synced_at) {
            const date = new Date(source.last_synced_at);
            if (!isNaN(date)) lastSync = date.toLocaleString();
        }

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
                        <button class="btn-secondary pause-btn" data-task-id="${t.id}">Pause</button>
                        <button class="btn-secondary cancel-btn" data-task-id="${t.id}" style="color: #dc3545;">Cancel</button>
                    `;
                } else if (status === "PAUSED") {
                    taskActions = `
                        <button class="btn-secondary resume-btn" data-task-id="${t.id}">Resume</button>
                        <button class="btn-secondary cancel-btn" data-task-id="${t.id}" style="color: #dc3545;">Cancel</button>
                    `;
                }

                taskHtml = `
                    <div class="task-progress-container">
                        <div style="display:flex; justify-content:space-between; font-size:0.85rem; font-weight: 600; color: #444;">
                            <span>${status === 'RUNNING' ? 'Syncing...' : status}</span>
                            <span>${finished} / ${t.total} Tracks</span>
                        </div>
                        <div class="task-progress-bar">
                            <div class="task-progress-fill" style="width:${percent}%"></div>
                        </div>
                        ${t.current ? `<div style="font-size: 0.8rem; color: #666; margin-top: 8px;">Downloading: ${t.current}</div>` : ""}
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
                <button class="btn-primary-outline sync-btn" data-id="${source.id}">Sync Now</button>
                <button class="toggle-btn" data-id="${source.id}" data-enabled="${source.enabled}">
                    ${source.enabled ? "Disable" : "Enable"}
                </button>
                <button class="delete-btn" data-id="${source.id}" style="color: #dc3545; margin-left: auto; border: none;">Delete</button>
            `;
        }

        const innerHTML = `
            <div class="source-header">
                <h3>${source.name}</h3>
                <span class="badge ${source.enabled ? "badge-completed" : "badge-queued"}">
                    ${source.enabled ? "Active" : "Disabled"}
                </span>
            </div>
            <div class="source-meta">
                <div><strong>Type:</strong> ${source.type}</div>
                <div><strong>Last Sync:</strong> ${lastSync}</div>
            </div>
            ${taskHtml}
            <div class="source-actions">
                ${actionsHtml}
            </div>
        `;

        // If card exists, update HTML, otherwise append new card
        if (card) {
            // Only update if HTML actually changed to prevent button flickering
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

    // Remove deleted sources
    const incomingIds = sources.map(s => `source-card-${s.id}`);
    Array.from(container.children).forEach(child => {
        if (!incomingIds.includes(child.id) && child.id.startsWith('source-card-')) {
            child.remove();
        }
    });

    bindEvents();
}

function bindEvents() {
    document.querySelectorAll(".sync-btn").forEach(btn => btn.onclick = syncSource);
    document.querySelectorAll(".toggle-btn").forEach(btn => btn.onclick = toggleSource);
    document.querySelectorAll(".delete-btn").forEach(btn => btn.onclick = deleteSource);
    
    document.querySelectorAll(".pause-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "pause"));
    document.querySelectorAll(".resume-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "resume"));
    document.querySelectorAll(".cancel-btn").forEach(btn => btn.onclick = (e) => handleTaskAction(e, "cancel"));
}

async function handleTaskAction(event, action) {
    const taskId = event.target.dataset.taskId;
    event.target.disabled = true;
    await fetch(`/api/tasks/${taskId}/${action}`, { method: "POST" });
}

async function deleteSource(event) {
    const id = event.target.dataset.id;
    if (!confirm("Delete this source?")) return;
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
    event.target.textContent = "Initiating...";
    const response = await fetch(`/api/sources/${id}/sync`, { method: "POST" });
    if (!response.ok) {
        alert("Sync failed.");
        event.target.disabled = false;
        event.target.textContent = "Sync Now";
    }
}

async function addSource(event) {
    event.preventDefault();
    const input = document.getElementById("source-url");
    const submitBtn = event.target.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = "Adding...";

    const response = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spotify_url: input.value }),
    });
    
    if (!response.ok) alert("Unable to add source.");
    
    input.value = "";
    submitBtn.disabled = false;
    submitBtn.textContent = "Add Source";
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
