function renderSources(sources) {
    const container = document.getElementById("sources");
    if (!container) return;

    if (sources.length === 0) {
        container.innerHTML = `
            <div class="panel empty-state">
                <h3>No sources yet</h3>
                <p>
                    Add your first Spotify playlist above to start syncing.
                </p>
            </div>
        `;
        return;
    }

    container.innerHTML = sources.map(source => {
        let taskHtml = "";
        let actionsHtml = "";
        let isTaskActive = false;

        // Check if there is a task and if it is currently in an active state
        if (source.task) {
            const t = source.task;
            const status = (t.status || "").toUpperCase();
            isTaskActive = ["QUEUED", "RUNNING", "PAUSED"].includes(status);
            
            if (isTaskActive) {
                const finished = t.completed + t.failed + t.skipped;
                const percent = t.total === 0 ? 0 : (finished / t.total) * 100;
                
                let taskActions = "";
                if (status === "RUNNING" || status === "QUEUED") {
                    taskActions = `
                        <button class="pause-btn" data-task-id="${t.id}" style="cursor:pointer; margin-right: 5px;">⏸️ Pause</button>
                        <button class="cancel-btn" data-task-id="${t.id}" style="cursor:pointer; color:red;">🛑 Cancel</button>
                    `;
                } else if (status === "PAUSED") {
                    taskActions = `
                        <button class="resume-btn" data-task-id="${t.id}" style="cursor:pointer; margin-right: 5px;">▶️ Resume</button>
                        <button class="cancel-btn" data-task-id="${t.id}" style="cursor:pointer; color:red;">🛑 Cancel</button>
                    `;
                }

                taskHtml = `
                    <div class="task-progress-container" style="margin: 15px 0; padding-top: 15px; border-top: 1px solid #eee;">
                        <div style="display:flex; justify-content:space-between; font-size:0.9rem; margin-bottom:8px;">
                            <strong>Status: ${status}</strong>
                            <span>${finished} / ${t.total} Tracks</span>
                        </div>
                        <div class="task-progress-bar">
                            <div class="task-progress-fill" style="width:${percent}%"></div>
                        </div>
                        ${t.current ? `<div style="font-size: 0.8rem; color: #666; margin-top: 5px;">Now downloading: ${t.current}</div>` : ""}
                        <div style="margin-top: 12px; display:flex;">
                            ${taskActions}
                        </div>
                    </div>
                `;
            }
        }

        // Only show standard controls if the task isn't currently hogging the UI
        if (!isTaskActive) {
            actionsHtml = `
                <button class="sync-btn" data-id="${source.id}">Sync Now</button>
                <button class="toggle-btn" data-id="${source.id}" data-enabled="${source.enabled}">
                    ${source.enabled ? "Disable" : "Enable"}
                </button>
                <button class="delete-btn" data-id="${source.id}">Delete</button>
            `;
        }

        // Format the date properly for the user
        let lastSync = "Never";
        if (source.last_synced_at) {
            const date = new Date(source.last_synced_at);
            if (!isNaN(date)) {
                lastSync = date.toLocaleString();
            }
        }

        return `
            <div class="source-card">
                <div class="source-header">
                    <h3>${source.name}</h3>
                    <span class="badge ${source.enabled ? "badge-enabled" : "badge-disabled"}">
                        ${source.enabled ? "Enabled" : "Disabled"}
                    </span>
                </div>
                <div class="source-meta">
                    <div>
                        <strong>Type</strong><br>
                        ${source.type}
                    </div>
                    <div>
                        <strong>Last Sync</strong><br>
                        ${lastSync}
                    </div>
                </div>
                ${taskHtml}
                <div class="source-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
    }).join("");

    // Re-attach event listeners to the newly rendered DOM elements
    bindEvents();
}

function bindEvents() {
    document.querySelectorAll(".sync-btn").forEach(btn => btn.addEventListener("click", syncSource));
    document.querySelectorAll(".toggle-btn").forEach(btn => btn.addEventListener("click", toggleSource));
    document.querySelectorAll(".delete-btn").forEach(btn => btn.addEventListener("click", deleteSource));
    
    // New Task Control Binders
    document.querySelectorAll(".pause-btn").forEach(btn => btn.addEventListener("click", (e) => handleTaskAction(e, "pause")));
    document.querySelectorAll(".resume-btn").forEach(btn => btn.addEventListener("click", (e) => handleTaskAction(e, "resume")));
    document.querySelectorAll(".cancel-btn").forEach(btn => btn.addEventListener("click", (e) => handleTaskAction(e, "cancel")));
}

async function handleTaskAction(event, action) {
    const taskId = event.target.dataset.taskId;
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
    event.target.textContent = "Syncing...";
    
    const response = await fetch(`/api/sources/${id}/sync`, { method: "POST" });
    if (!response.ok) alert("Sync failed.");
}

async function addSource(event) {
    event.preventDefault();
    const input = document.getElementById("source-url");
    const response = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spotify_url: input.value }),
    });
    
    if (!response.ok) {
        alert("Unable to add source.");
        return;
    }
    input.value = "";
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
