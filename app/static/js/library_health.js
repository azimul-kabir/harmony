const healthState = { taskId: null, timer: null };
const actionCopy = {
    refresh: ["Refresh Library?", "Harmony will scan the music folder incrementally and reconcile missing files."],
    rebuild: ["Rebuild the Library Index?", "Harmony will re-read metadata for every music file and rebuild indexed search."],
    verify: ["Verify indexed files?", "Harmony will check every known file path and update missing or modified records."],
    clear_artwork: ["Clear the artwork cache?", "Cached artwork files and associations will be removed. A later metadata refresh can recreate local artwork."],
};

async function healthJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed: ${response.status}`);
    }
    return response.json();
}

async function loadHealth() {
    try {
        const health = await healthJson("/api/library/health");
        const values = {
            songs: Number(health.songs || 0).toLocaleString(),
            albums: Number(health.albums || 0).toLocaleString(),
            artists: Number(health.artists || 0).toLocaleString(),
            storage: formatHealthBytes(health.storage_bytes),
            artwork: Number(health.missing_artwork || 0).toLocaleString(),
            metadata: Number(health.missing_metadata || 0).toLocaleString(),
            duplicates: health.duplicates == null ? "Coming soon" : Number(health.duplicates).toLocaleString(),
            updated: formatHealthDate(health.last_updated),
        };
        Object.entries(values).forEach(([key, value]) => {
            document.getElementById(`health-${key}`).textContent = value;
        });
        document.getElementById("health-score").textContent = health.health_score;
        document.getElementById("health-score-ring").style.setProperty("--health-score", `${health.health_score * 3.6}deg`);
        renderHealthChecks(health.checks || []);
        await loadLibraryJobs();
        document.getElementById("health-error").hidden = true;
    } catch (error) {
        const box = document.getElementById("health-error");
        box.textContent = `Harmony could not load Library health: ${error.message}`;
        box.hidden = false;
    }
}

async function loadLibraryJobs() {
    const [active, recent] = await Promise.all([
        healthJson("/api/tasks/jobs/active"),
        healthJson("/api/tasks/library-activity?limit=8"),
    ]);
    const renderJobs = (target, jobs, empty) => {
        target.innerHTML = jobs.length ? jobs.map((job) => `<article class="health-check status-${escapeHealth(job.status)}">
      <span class="health-check-indicator" aria-hidden="true"></span><div><strong>${escapeHealth(job.name)}</strong><small>${escapeHealth(job.status)} · ${job.processed}/${job.total}${job.error_code ? ` · ${escapeHealth(job.error_code)}` : ""}</small></div>
      ${["queued", "running", "cancelling"].includes(job.status) ? `<button class="btn-secondary" data-job-cancel="${job.id}">Cancel</button>` : ""}</article>`).join("") : `<p>${empty}</p>`;
    };
    const activeTarget = document.getElementById("library-active-jobs");
    renderJobs(activeTarget, active, "No active jobs.");
    renderJobs(document.getElementById("library-recent-activity"), recent, "No recent activity.");
    activeTarget.querySelectorAll("[data-job-cancel]").forEach((button) => button.addEventListener("click", async () => {
        await healthJson(`/api/tasks/jobs/${button.dataset.jobCancel}/cancel`, {method: "POST"});
        loadLibraryJobs();
    }));
}

function renderHealthChecks(checks) {
    document.getElementById("health-check-list").innerHTML = checks.map((check) => `
        <article class="health-check status-${check.status}">
            <span class="health-check-indicator" aria-hidden="true"></span>
            <div><strong>${escapeHealth(check.label)}</strong><small>${check.available ?
                (check.count ? `${Number(check.count).toLocaleString()} songs need attention` : "No issues detected") :
                "Provider not installed yet"}</small></div>
            <span>${check.available ? (check.status === "healthy" ? "Healthy" : "Review") : "Future"}</span>
        </article>
    `).join("");
}

function showHealthConfirmation(action) {
    const [title, message] = actionCopy[action];
    const dialog = document.getElementById("health-confirm");
    dialog.dataset.action = action;
    document.getElementById("health-confirm-title").textContent = title;
    document.getElementById("health-confirm-message").textContent = message;
    document.getElementById("health-confirm-run").classList.toggle("library-danger-button", action === "clear_artwork");
    dialog.showModal();
}

async function runHealthAction(action) {
    const task = await healthJson(`/api/library/health/actions/${action}`, { method: "POST" });
    healthState.taskId = task.id;
    renderHealthTask(task);
    pollHealthTask();
}

async function pollHealthTask() {
    clearTimeout(healthState.timer);
    if (!healthState.taskId) return;
    try {
        const task = await healthJson(`/api/library/health/tasks/${healthState.taskId}`);
        renderHealthTask(task);
        if (["completed", "completed_with_errors", "failed", "cancelled", "interrupted"].includes(task.status)) {
            await loadHealth();
            return;
        }
        healthState.timer = setTimeout(pollHealthTask, 700);
    } catch (error) {
        document.getElementById("health-task-current").textContent = "Progress unavailable; retrying…";
        healthState.timer = setTimeout(pollHealthTask, 1500);
    }
}

function renderHealthTask(task) {
    const terminal = ["completed", "completed_with_errors", "failed", "cancelled", "interrupted"].includes(task.status);
    document.getElementById("health-task").hidden = false;
    document.getElementById("health-task-name").textContent = task.name;
    document.getElementById("health-task-count").textContent = `${task.processed} of ${task.total}`;
    document.getElementById("health-task-progress").value = task.progress;
    document.getElementById("health-task-current").textContent = terminal
        ? `${task.completed} completed · ${task.failed} failed · ${task.skipped} cancelled`
        : task.current || "Queued for background processing…";
    document.getElementById("health-task-cancel").hidden = terminal;
    document.getElementById("health-task-dismiss").hidden = !terminal;
}

function formatHealthBytes(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** unit)).toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function formatHealthDate(value) {
    if (!value) return "Never indexed";
    const date = new Date(value.endsWith?.("Z") ? value : `${value}Z`);
    return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function escapeHealth(value) {
    return String(value ?? "").replace(/[&<>\"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[char]);
}

document.querySelectorAll("[data-health-action]").forEach((button) => {
    button.addEventListener("click", () => showHealthConfirmation(button.dataset.healthAction));
});
document.getElementById("health-confirm-run").addEventListener("click", async (event) => {
    event.preventDefault();
    const dialog = document.getElementById("health-confirm");
    event.currentTarget.disabled = true;
    try {
        await runHealthAction(dialog.dataset.action);
        dialog.close();
    } catch (error) {
        document.getElementById("health-confirm-message").textContent = error.message;
    } finally {
        event.currentTarget.disabled = false;
    }
});
document.getElementById("health-task-cancel").addEventListener("click", async () => {
    await healthJson(`/api/library/health/tasks/${healthState.taskId}/cancel`, { method: "POST" });
    pollHealthTask();
});
document.getElementById("health-task-dismiss").addEventListener("click", () => {
    document.getElementById("health-task").hidden = true;
    healthState.taskId = null;
});
document.addEventListener("DOMContentLoaded", loadHealth);
