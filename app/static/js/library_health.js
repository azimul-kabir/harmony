const healthState = {
    taskId: null,
    timer: null,
    attentionJobs: false,
    jobType: null,
    recentJobs: [],
    recentVisible: 10,
};
const healthCheckDestinations = {
    artwork: "/library?missing_artwork=true",
    metadata: "/library?missing_metadata=true",
    missing_files: "/library?availability=missing",
};
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
        const detail = body.detail?.error || body.error || body.detail;
        throw new Error(detail?.message || detail || `Request failed: ${response.status}`);
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
    const pageParams = new URLSearchParams(window.location.search);
    const attentionOnly = pageParams.get("job_status") === "attention";
    const requestedType = pageParams.get("job_type");
    healthState.attentionJobs = attentionOnly;
    healthState.jobType = ["library_bulk", "library_maintenance"].includes(requestedType)
        ? requestedType
        : null;
    const activityParams = new URLSearchParams({
        limit: "100",
    });
    if (attentionOnly) activityParams.set("attention_only", "true");
    if (["library_bulk", "library_maintenance"].includes(requestedType)) {
        activityParams.set("job_type", requestedType);
    }
    const typeLabel = requestedType === "library_bulk"
        ? "bulk"
        : requestedType === "library_maintenance" ? "maintenance" : "Library";
    document.getElementById("library-jobs-description").textContent = attentionOnly
        ? `Showing all ${typeLabel} jobs that require attention`
        : "Active and recent persistent operations";
    const acknowledgeAll = document.getElementById("library-jobs-acknowledge-all");
    acknowledgeAll.hidden = !attentionOnly || !healthState.jobType;
    const [active, recent] = await Promise.all([
        healthJson("/api/tasks/jobs/active"),
        healthJson(`/api/tasks/library-activity?${activityParams}`),
    ]);
    acknowledgeAll.hidden = !attentionOnly || !healthState.jobType || recent.length === 0;
    acknowledgeAll.textContent = "Mark all shown reviewed";
    const renderJobs = (target, jobs, empty) => {
        target.innerHTML = jobs.length ? jobs.map((job) => `<article class="health-check status-${escapeHealth(job.status)}">
      <span class="health-check-indicator" aria-hidden="true"></span><div><strong>${escapeHealth(job.name)}</strong><small>${escapeHealth(job.status)} · ${job.processed}/${job.total}${job.error_code ? ` · ${escapeHealth(job.error_code)}` : ""}</small></div>
      <div class="library-job-actions"><button class="btn-secondary" data-job-details="${job.id}">Details</button>${["queued", "running", "cancelling"].includes(job.status) ? `<button class="btn-secondary" data-job-cancel="${job.id}">Cancel</button>` : ""}</div></article>`).join("") : `<p>${empty}</p>`;
    };
    const bindJobDetails = (target) => {
        target.querySelectorAll("[data-job-details]").forEach((button) => {
            button.addEventListener("click", () => openLibraryJobDetails(button.dataset.jobDetails));
        });
    };
    const renderRecentJobs = () => {
        const recentTarget = document.getElementById("library-recent-activity");
        const visible = healthState.attentionJobs
            ? healthState.recentJobs
            : healthState.recentJobs.slice(0, healthState.recentVisible);
        renderJobs(
            recentTarget,
            visible,
            healthState.attentionJobs
                ? `No ${typeLabel} jobs currently require attention.`
                : "No recent activity.",
        );
        bindJobDetails(recentTarget);
        const showMore = document.getElementById("library-activity-show-more");
        showMore.hidden = healthState.attentionJobs
            || healthState.recentVisible >= healthState.recentJobs.length;
        const remaining = Math.max(0, healthState.recentJobs.length - healthState.recentVisible);
        showMore.textContent = `Show ${Math.min(10, remaining)} more`;
    };
    const activeTarget = document.getElementById("library-active-jobs");
    renderJobs(activeTarget, active, "No active jobs.");
    healthState.recentJobs = recent;
    healthState.recentVisible = 10;
    renderRecentJobs();
    activeTarget.querySelectorAll("[data-job-cancel]").forEach((button) => button.addEventListener("click", async () => {
        await healthJson(`/api/tasks/jobs/${button.dataset.jobCancel}/cancel`, {method: "POST"});
        loadLibraryJobs();
    }));
    bindJobDetails(activeTarget);
    const showMore = document.getElementById("library-activity-show-more");
    showMore.onclick = () => {
        healthState.recentVisible += 10;
        renderRecentJobs();
    };
}

async function openLibraryJobDetails(taskId) {
    const dialog = document.getElementById("library-job-dialog");
    document.getElementById("library-job-title").textContent = "Library job";
    document.getElementById("library-job-summary").textContent = "Loading diagnostics…";
    document.getElementById("library-job-facts").replaceChildren();
    document.getElementById("library-job-failures").replaceChildren();
    const acknowledge = document.getElementById("library-job-acknowledge");
    acknowledge.hidden = true;
    acknowledge.dataset.taskId = "";
    dialog.showModal();
    try {
        const [job, failures] = await Promise.all([
            healthJson(`/api/tasks/jobs/${taskId}`),
            healthJson(`/api/tasks/jobs/${taskId}/failures?limit=100`),
        ]);
        document.getElementById("library-job-title").textContent = job.name || "Library job";
        acknowledge.hidden = !["completed_with_errors", "failed", "interrupted"].includes(job.status)
            || Boolean(job.reviewed_at);
        acknowledge.dataset.taskId = String(job.id);
        document.getElementById("library-job-summary").textContent =
            job.error_summary || (
                job.status === "interrupted"
                    ? "Harmony stopped before this job could finish. Run the operation again when no conflicting Library job is active."
                    : job.failed
                        ? `${job.failed} item${job.failed === 1 ? "" : "s"} failed. Review the item details below.`
                        : "This job has no recorded error summary."
            );
        const facts = [
            ["Status", String(job.status || "unknown").replaceAll("_", " ")],
            ["Job type", String(job.type || "unknown").replaceAll("_", " ")],
            ["Progress", `${job.processed} of ${job.total}`],
            ["Completed", String(job.completed || 0)],
            ["Failed", String(job.failed || 0)],
            ["Skipped", String(job.skipped || 0)],
            ["Started", formatHealthDate(job.started_at)],
            ["Finished", formatHealthDate(job.completed_at)],
            ["Error code", job.error_code || "None recorded"],
        ];
        const factsTarget = document.getElementById("library-job-facts");
        facts.forEach(([label, value]) => {
            const term = document.createElement("dt");
            const detail = document.createElement("dd");
            term.textContent = label;
            detail.textContent = value;
            factsTarget.append(term, detail);
        });
        const failuresTarget = document.getElementById("library-job-failures");
        if (!failures.items.length) {
            const empty = document.createElement("p");
            empty.textContent = job.error_summary
                ? "No item-level failures were recorded for this job."
                : "No failure details were recorded.";
            failuresTarget.appendChild(empty);
        } else {
            failures.items.forEach((failure) => {
                const item = document.createElement("article");
                const title = document.createElement("strong");
                const code = document.createElement("small");
                const message = document.createElement("p");
                title.textContent = failure.item || "Unknown item";
                code.textContent = `${failure.error_code || "ERROR"} · ${formatHealthDate(failure.created_at)}`;
                message.textContent = failure.message || "No additional explanation was recorded.";
                item.append(title, code, message);
                failuresTarget.appendChild(item);
            });
        }
    } catch (error) {
        document.getElementById("library-job-summary").textContent =
            `Harmony could not load these diagnostics: ${error.message}`;
    }
}

document.getElementById("library-job-acknowledge")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!button.dataset.taskId) return;
    button.disabled = true;
    button.textContent = "Marking…";
    try {
        await healthJson(`/api/tasks/jobs/${button.dataset.taskId}/acknowledge`, {
            method: "POST",
        });
        document.getElementById("library-job-dialog").close();
        await loadLibraryJobs();
    } catch (error) {
        document.getElementById("library-job-summary").textContent =
            `Harmony could not mark this job reviewed: ${error.message}`;
    } finally {
        button.disabled = false;
        button.textContent = "Mark reviewed";
    }
});

document.getElementById("library-activity-clear-open")?.addEventListener("click", () => {
    document.getElementById("library-activity-clear-reviewed").checked = false;
    document.getElementById("library-activity-clear-status").textContent = "";
    document.getElementById("library-activity-clear-dialog").showModal();
});

document.getElementById("library-activity-clear-confirm")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const includeReviewed = document.getElementById("library-activity-clear-reviewed").checked;
    button.disabled = true;
    button.textContent = "Clearing…";
    try {
        const result = await healthJson("/api/tasks/jobs/clear", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({include_reviewed_attention: includeReviewed}),
        });
        document.getElementById("library-activity-clear-status").textContent =
            result.cleared
                ? `${result.cleared} activit${result.cleared === 1 ? "y" : "ies"} cleared.`
                : "No eligible activity to clear.";
        await loadLibraryJobs();
        window.setTimeout(() => {
            document.getElementById("library-activity-clear-dialog").close();
        }, 550);
    } catch (error) {
        document.getElementById("library-activity-clear-status").textContent = error.message;
    } finally {
        button.disabled = false;
        button.textContent = "Clear activity";
    }
});

document.getElementById("library-jobs-acknowledge-all")?.addEventListener("click", async (event) => {
    if (!healthState.jobType) return;
    const typeLabel = healthState.jobType === "library_bulk" ? "bulk" : "maintenance";
    if (!window.confirm(
        `Mark all shown ${typeLabel} job warnings as reviewed?\n\n` +
        "Their history and diagnostics will remain available in Recent activity."
    )) return;
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Marking…";
    try {
        const result = await healthJson("/api/tasks/jobs/acknowledge", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({job_type: healthState.jobType}),
        });
        button.textContent = `${result.acknowledged} reviewed`;
        await loadLibraryJobs();
    } catch (error) {
        button.textContent = "Try again";
    } finally {
        button.disabled = false;
    }
});

function renderHealthChecks(checks) {
    document.getElementById("health-check-list").innerHTML = checks.map((check) => `
        <article class="health-check status-${check.status}">
            <span class="health-check-indicator" aria-hidden="true"></span>
            <div><strong>${escapeHealth(check.label)}</strong><small>${check.available ?
                (check.count ? `${Number(check.count).toLocaleString()} songs need attention` : "No issues detected") :
                "Provider not installed yet"}</small></div>
            ${renderHealthCheckAction(check)}
        </article>
    `).join("");
}

function renderHealthCheckAction(check) {
    if (!check.available) return "<span>Future</span>";
    if (check.status === "healthy") return "<span>Healthy</span>";

    const destination = healthCheckDestinations[check.id];
    return destination
        ? `<a class="btn-secondary health-check-action" href="${destination}" aria-label="Review ${escapeHealth(check.label)}">Review</a>`
        : "<span>Review</span>";
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
document.addEventListener("DOMContentLoaded", () => {
    loadHealth();
});
