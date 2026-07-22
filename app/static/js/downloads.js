let currentJobs = [];
const DOWNLOAD_FILTERS = new Set(["ALL", "ACTIVE", "RUNNING", "QUEUED", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"]);
let currentFilter = "ALL";
let searchQuery = "";

function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = Number(value || 0).toLocaleString(); }
function statusOf(job) { return String(job.status || "").toUpperCase(); }
function setDownloadFilter(filter, push = true) {
    currentFilter = DOWNLOAD_FILTERS.has(filter) ? filter : "ALL";
    document.querySelectorAll(".filter-tab, [data-summary-filter]").forEach((item) => item.classList.toggle("active", item.dataset.filter === currentFilter));
    const url = new URL(window.location.href);
    currentFilter === "ALL" ? url.searchParams.delete("status") : url.searchParams.set("status", currentFilter.toLowerCase());
    window.history[push ? "pushState" : "replaceState"]({}, "", url);
    renderHistory();
}
function filteredJobs() {
    let jobs = currentJobs.filter((job) => {
        const status = statusOf(job);
        if (currentFilter === "ALL") return true;
        if (currentFilter === "ACTIVE") return ["RUNNING", "QUEUED", "PAUSED"].includes(status);
        if (currentFilter === "COMPLETED") return ["COMPLETED", "SKIPPED"].includes(status);
        if (currentFilter === "FAILED") return ["FAILED", "CANCELLED"].includes(status);
        return status === currentFilter;
    });
    if (searchQuery) { const q = searchQuery.toLowerCase(); jobs = jobs.filter((j) => [j.title, j.artist, j.album].some((v) => String(v || "").toLowerCase().includes(q))); }
    return jobs;
}
function renderHistory() {
    const tbody = document.getElementById("downloads-body"); if (!tbody) return;
    const jobs = filteredJobs(); const ids = new Set(jobs.map((j) => String(j.id)));
    tbody.querySelectorAll("tr[data-download-id]").forEach((row) => { if (!ids.has(row.dataset.downloadId)) row.remove(); });
    if (!jobs.length) { const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 5; cell.className = "text-center empty-state"; cell.style.padding = "40px"; cell.textContent = "No recent downloads match this filter."; row.appendChild(cell); tbody.replaceChildren(row); }
    else { tbody.querySelectorAll("tr:not([data-download-id])").forEach((row) => row.remove()); jobs.forEach((job) => patchHistoryRow(tbody, job)); }
    const label = document.getElementById("downloads-visible-count"); if (label) label.textContent = `${jobs.length.toLocaleString()} of ${currentJobs.length.toLocaleString()} recent downloads shown`;
}
function patchHistoryRow(tbody, job) {
    let row = tbody.querySelector(`tr[data-download-id="${job.id}"]`);
    if (!row) { row = document.createElement("tr"); row.dataset.downloadId = String(job.id); row.innerHTML = '<td class="download-status-cell"></td><td><strong class="download-title"></strong></td><td class="download-artist-cell"></td><td class="download-album-cell"></td><td></td>'; tbody.appendChild(row); }
    const status = statusOf(job), badge = document.createElement("span"); badge.className = `badge badge-${status.toLowerCase()}`; badge.textContent = status === "RUNNING" ? "Downloading" : status || "Unknown";
    row.querySelector(".download-status-cell").replaceChildren(badge); row.querySelector(".download-title").textContent = job.title || "Unknown title"; row.querySelector(".download-artist-cell").textContent = job.artist || "—"; row.querySelector(".download-album-cell").textContent = job.album || "—";
}
function queueItem(job, active) {
    const item = document.createElement(active ? "article" : "li"); item.className = active ? "active-download-card" : "queue-item"; item.dataset.downloadId = String(job.id);
    const title = document.createElement("strong"); title.textContent = job.title || "Unknown title"; const artist = document.createElement("span"); artist.className = "queue-artist"; artist.textContent = job.artist || "Unknown artist"; item.append(title, artist);
    if (active && job.started_at) { const elapsed = document.createElement("small"); elapsed.className = "queue-elapsed"; elapsed.dataset.startedAt = job.started_at; item.appendChild(elapsed); }
    if (active) { const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn-danger queue-cancel"; cancel.textContent = "Cancel"; cancel.addEventListener("click", () => cancelDownload(job.id)); item.appendChild(cancel); }
    return item;
}
function patchQueue(containerId, emptyId, jobs, active) {
    const container = document.getElementById(containerId), empty = document.getElementById(emptyId); if (!container || !empty) return;
    const ids = new Set(jobs.map((j) => String(j.id))); container.querySelectorAll("[data-download-id]").forEach((node) => { if (!ids.has(node.dataset.downloadId)) node.remove(); });
    jobs.forEach((job) => { let node = container.querySelector(`[data-download-id="${job.id}"]`); if (!node) { node = queueItem(job, active); container.appendChild(node); } else { const values = node.querySelectorAll("strong, .queue-artist"); values[0].textContent = job.title || "Unknown title"; values[1].textContent = job.artist || "Unknown artist"; } });
    empty.hidden = jobs.length > 0;
}
function updateElapsed() { document.querySelectorAll(".queue-elapsed").forEach((node) => { const start = Date.parse(node.dataset.startedAt); if (!Number.isNaN(start)) node.textContent = `Running for ${Math.max(0, Math.floor((Date.now() - start) / 60000))} min`; }); }
async function cancelDownload(id) { const response = await fetch(`/api/downloads/${id}/cancel`, { method: "POST" }); if (!response.ok) return; }
function applySnapshot(snapshot) { currentJobs = snapshot.jobs || []; const counts = snapshot.counts || {}; ["running", "queued", "paused", "completed", "failed", "cancelled"].forEach((key) => setText(`downloads-${key}`, counts[key])); patchQueue("active-downloads", "active-downloads-empty", snapshot.active || [], true); patchQueue("waiting-downloads", "waiting-downloads-empty", snapshot.queued || [], false); patchQueue("paused-downloads", "paused-downloads-empty", snapshot.paused || [], false); updateElapsed(); renderHistory(); }
function connectDownloadsSSE() { const source = new EventSource("/api/downloads/stream"); source.onmessage = (event) => applySnapshot(JSON.parse(event.data)); }

document.querySelectorAll(".filter-tab, [data-summary-filter]").forEach((item) => item.addEventListener("click", () => setDownloadFilter(item.dataset.filter)));
document.getElementById("search-input")?.addEventListener("input", (event) => { searchQuery = event.target.value.trim(); renderHistory(); });
window.addEventListener("popstate", () => setDownloadFilter(new URLSearchParams(location.search).get("status")?.toUpperCase() || "ALL", false));
const requested = new URLSearchParams(location.search).get("status")?.toUpperCase(); setDownloadFilter(requested || "ALL", false); setInterval(updateElapsed, 60000); connectDownloadsSSE();

const downloadForm = document.getElementById("download-form");
downloadForm?.addEventListener("submit", async (event) => {
    event.preventDefault(); const input = document.getElementById("spotify-url"); const result = document.getElementById("download-result");
    try { const response = await fetch("/api/downloads", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: input.value }) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Download failed."); result.textContent = data.status === "owned" ? "This track already exists in your library." : "Download queued successfully."; input.value = ""; }
    catch (error) { result.textContent = error.message || "Download failed."; }
});
document.getElementById("clear-history-btn")?.addEventListener("click", async () => { if (!confirm("Are you sure you want to clear all completed and failed history?")) return; const response = await fetch("/api/downloads/clear", { method: "POST" }); document.getElementById("download-result").textContent = response.ok ? "Completed, failed, skipped, and cancelled history cleared." : "Failed to clear history."; });
