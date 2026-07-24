const healthState = {
    taskId: null,
    timer: null,
    attentionJobs: false,
    jobType: null,
    recentJobs: [],
    recentVisible: 10,
    selectedIssues: new Set(),
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
        await loadMetadataIssues();
        await loadLibraryJobs();
        document.getElementById("health-error").hidden = true;
    } catch (error) {
        const box = document.getElementById("health-error");
        box.textContent = `Harmony could not load Library health: ${error.message}`;
        box.hidden = false;
    }
}

async function loadMetadataIssues() {
    const status = document.getElementById("metadata-status")?.value || "open";
    const severity = document.getElementById("metadata-severity")?.value || "";
    const query = document.getElementById("metadata-search")?.value || "";
    const entityType = document.getElementById("metadata-entity")?.value || "";
    const params = new URLSearchParams({ status, limit: "50" });
    if (status === "open") params.set("included_only", "true");
    if (severity) params.set("severity", severity);
    if (entityType) params.set("entity_type", entityType);
    if (query) params.set("search", query);
    const data = await healthJson(`/api/library/health/metadata/issues?${params}`);
    const target = document.getElementById("metadata-issues");
    const items = data.items;
    target.innerHTML = items.length ? items.map((item) => {
        const destination = item.entity_type === "song" && item.song_id
            ? `<a class="btn-secondary" href="/library?song=${item.song_id}&metadata=review">Review song</a>`
            : item.entity_type === "album" && item.album_key
                ? `<a class="btn-secondary" href="/library?view=albums&album_key=${encodeURIComponent(item.album_key)}">Open album</a>` : "";
        const action = item.status === "ignored"
            ? `<button class="btn-secondary" data-metadata-restore="${item.id}">Restore</button>`
            : item.status === "open" ? `<button class="btn-secondary" data-metadata-ignore="${item.id}">Ignore</button>` : "";
        const discoverable = ["missing_musicbrainz_recording_id","missing_musicbrainz_release_id","missing_musicbrainz_artist_id","missing_title","placeholder_title","filename_derived_title","missing_artist","placeholder_artist","missing_album","placeholder_album","missing_genre","suspicious_whitespace","inconsistent_capitalization"].includes(item.rule_id);
        const discover = discoverable ? `<label class="metadata-repair-select"><input type="checkbox" data-select-issue="${item.id}" ${healthState.selectedIssues.has(item.id) ? "checked" : ""}> Select for repair</label><button class="btn-secondary" data-discover-issue="${item.id}">Find candidates</button>` : "";
        return `<details class="health-check status-${escapeHealth(item.severity)}"><summary><span class="health-check-indicator"></span><div><strong>${escapeHealth(item.title)}</strong><small>${escapeHealth(item.rule_id)} · ${escapeHealth(item.entity_type)} · ${escapeHealth(item.severity)}</small></div></summary><p>${escapeHealth(item.explanation)}</p><p><strong>Next action:</strong> ${escapeHealth(item.suggested_action)}</p><div>${destination}${action}${discover}</div></details>`;
    }).join("") : `<p>${status === "open" ? "No open metadata issues. Run an analysis to refresh results." : `No ${escapeHealth(status)} metadata issues match these filters.`}</p>`;
    target.querySelectorAll("[data-metadata-ignore]").forEach((button) => button.onclick = async () => { await healthJson(`/api/library/health/metadata/issues/${button.dataset.metadataIgnore}/ignore`, {method:"POST"}); loadMetadataIssues(); });
    target.querySelectorAll("[data-metadata-restore]").forEach((button) => button.onclick = async () => { await healthJson(`/api/library/health/metadata/issues/${button.dataset.metadataRestore}/restore`, {method:"POST"}); loadMetadataIssues(); });
    target.querySelectorAll("[data-metadata-resolve]").forEach((button) => button.onclick = async () => { await healthJson(`/api/library/health/metadata/issues/${button.dataset.metadataResolve}/resolve`, {method:"POST"}); loadMetadataIssues(); });
    target.querySelectorAll("[data-select-issue]").forEach((checkbox) => checkbox.onchange = () => {
        const issueId=Number(checkbox.dataset.selectIssue);
        checkbox.checked ? healthState.selectedIssues.add(issueId) : healthState.selectedIssues.delete(issueId);
        updateRepairSelection();
    });
    target.querySelectorAll("[data-discover-issue]").forEach((button) => button.onclick = async () => {
        const provider=document.getElementById("metadata-repair-provider").value;
        const result=await healthJson("/api/metadata/discoveries/health-issues",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({issue_ids:[Number(button.dataset.discoverIssue)],provider,initiated_by:"library-health-ui"})});
        button.textContent=`Candidate search queued (job ${result.job.id})`;button.disabled=true;
        healthState.taskId=result.job.id;renderHealthTask(result.job);pollHealthTask();
    });
    updateRepairSelection();
    const summary = await healthJson("/api/library/health/metadata/summary");
    document.getElementById("metadata-score-detail").textContent = `Metadata score ${summary.score.score}/100 · ${summary.score.inputs.included_open_issues} included open issue records · ${summary.score.inputs.ignored_issues} ignored historical records (diagnostic only). Warnings reduce this score.`;
    const severityCounts = Object.fromEntries((summary.counts.severity || []).map((row) => [row.value, row.count]));
    document.querySelectorAll("[data-metadata-severity-count]").forEach((count) => {
        count.textContent = Number(severityCounts[count.dataset.metadataSeverityCount] || 0).toLocaleString();
    });
    const ruleCounts = (summary.counts.rule || []).sort((a, b) => b.count - a.count || String(a.value).localeCompare(String(b.value))).slice(0, 8);
    const ruleSummary = document.getElementById("metadata-rule-counts");
    ruleSummary.classList.toggle("is-empty", !ruleCounts.length);
    const ruleIcon = document.createElement("span");
    ruleIcon.className = "metadata-rule-icon";
    ruleIcon.setAttribute("aria-hidden", "true");
    ruleIcon.textContent = ruleCounts.length ? "↗" : "✓";
    const ruleCopy = document.createElement("div");
    const ruleTitle = document.createElement("strong");
    const ruleDetail = document.createElement("small");
    if (ruleCounts.length) {
        ruleTitle.textContent = ruleCounts[0].value.replaceAll("_", " ");
        ruleDetail.textContent = `${Number(ruleCounts[0].count).toLocaleString()} issue records${ruleCounts.length > 1 ? ` · ${ruleCounts.length - 1} more rules` : ""}`;
    } else {
        ruleTitle.textContent = "No recurring rule patterns";
        ruleDetail.textContent = "Run metadata analysis to populate this summary.";
    }
    ruleCopy.append(ruleTitle, ruleDetail);
    ruleSummary.replaceChildren(ruleIcon, ruleCopy);
}

function updateRepairSelection() {
    const count=healthState.selectedIssues.size;
    document.getElementById("metadata-repair-count").textContent=String(count);
    document.getElementById("metadata-repair-selected").disabled=!count;
    document.getElementById("metadata-repair-clear").disabled=!count;
}

async function loadRepairProviders() {
    try {
        const data=await healthJson("/api/providers/status");
        const byName=Object.fromEntries(data.providers.map((item)=>[item.provider,item]));
        const select=document.getElementById("metadata-repair-provider");
        [...select.options].forEach((option)=>{
            const available=byName[option.value]?.available !== false;
            option.disabled=!available;
            option.textContent=`${option.value === "musicbrainz" ? "MusicBrainz" : "Spotify"}${available ? "" : " (not configured)"}`;
        });
        if (select.selectedOptions[0]?.disabled) select.value="musicbrainz";
    } catch (_) { /* MusicBrainz remains the conservative default. */ }
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
    const requestedStatus = new URLSearchParams(window.location.search).get("metadata_status");
    const status = document.getElementById("metadata-status");
    if (requestedStatus && status && [...status.options].some((option) => option.value === requestedStatus)) status.value = requestedStatus;
    loadRepairProviders();
    loadHealth();
});
document.getElementById("metadata-repair-selected")?.addEventListener("click", async (event) => {
    const button=event.currentTarget;button.disabled=true;
    try {
        const provider=document.getElementById("metadata-repair-provider").value;
        const result=await healthJson("/api/metadata/discoveries/health-issues",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({issue_ids:[...healthState.selectedIssues],provider,initiated_by:"library-health-ui"})});
        healthState.selectedIssues.clear();updateRepairSelection();
        healthState.taskId=result.job.id;renderHealthTask(result.job);pollHealthTask();
    } catch (error) {
        document.getElementById("health-error").textContent=`Repair discovery could not start: ${error.message}`;
        document.getElementById("health-error").hidden=false;
    } finally { updateRepairSelection(); }
});
document.getElementById("metadata-repair-clear")?.addEventListener("click", () => {
    healthState.selectedIssues.clear();
    document.querySelectorAll("[data-select-issue]").forEach((item)=>{item.checked=false;});
    updateRepairSelection();
});
document.getElementById("metadata-analysis")?.addEventListener("click", async () => { const task = await healthJson("/api/library/health/metadata/analyze", {method:"POST"}); healthState.taskId=task.id; renderHealthTask(task); pollHealthTask(); });
document.getElementById("metadata-status")?.addEventListener("change", loadMetadataIssues);
document.getElementById("metadata-severity")?.addEventListener("change", (event) => {
    document.querySelectorAll("[data-metadata-severity-filter]").forEach((chip) => {
        chip.classList.toggle("is-selected", chip.dataset.metadataSeverityFilter === event.target.value);
    });
    loadMetadataIssues();
});
document.querySelectorAll("[data-metadata-severity-filter]").forEach((button) => {
    button.addEventListener("click", () => {
        const select = document.getElementById("metadata-severity");
        const next = button.dataset.metadataSeverityFilter;
        select.value = select.value === next ? "" : next;
        document.querySelectorAll("[data-metadata-severity-filter]").forEach((chip) => {
            chip.classList.toggle("is-selected", chip.dataset.metadataSeverityFilter === select.value);
        });
        loadMetadataIssues();
    });
});
document.getElementById("metadata-entity")?.addEventListener("change", loadMetadataIssues);
let metadataSearchTimer;
document.getElementById("metadata-search")?.addEventListener("input", () => {
    clearTimeout(metadataSearchTimer);
    metadataSearchTimer = setTimeout(loadMetadataIssues, 250);
});
