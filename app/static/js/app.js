// Shared JavaScript for Harmony
const SUBMIT_LABEL = "Start download";

document.addEventListener("DOMContentLoaded", () => {
    // --- 1. Global Mini Player Management ---
    const miniPlayer = document.getElementById("global-mini-player");
    const titleEl = document.getElementById("mp-title");
    const statusEl = document.getElementById("mp-status");
    const progressFill = document.getElementById("mp-progress");
    const countEl = document.getElementById("mp-count");

    // Hook into the existing Dashboard stream globally
    const eventSource = new EventSource("/api/dashboard/stream");
    
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        // Find tasks that are actively processing
        const activeTasks = (data.tasks || []).filter(t => 
            t.status.toUpperCase() === "RUNNING" || 
            t.status.toUpperCase() === "QUEUED"
        );
        
        if (activeTasks.length > 0) {
            const task = activeTasks[0]; 
            const finished = task.completed + task.failed + task.skipped;
            const percent = task.total === 0 ? 0 : (finished / task.total) * 100;

            titleEl.textContent = task.current ? task.current : task.name;
            statusEl.innerHTML = task.status.toUpperCase() === "RUNNING" 
                ? '<span class="spinner" style="width:10px; height:10px; border-width:2px; margin-right:4px;"></span> Downloading'
                : 'Queued';
            
            progressFill.style.width = `${percent}%`;
            countEl.textContent = `${finished} / ${task.total}`;

            miniPlayer.classList.remove("hidden");
        } else {
            miniPlayer.classList.add("hidden");
        }
    };

    // --- 2. Global Floating Action Modal Logic ---
    const fabBtn = document.getElementById("global-fab");
    const modal = document.getElementById("download-modal");
    const closeBtn = document.getElementById("modal-close-btn");
    const modalForm = document.getElementById("modal-download-form");
    const modalInput = document.getElementById("modal-spotify-url");
    const modalSubmit = document.getElementById("modal-submit-btn");
    const resultBox = document.getElementById("modal-result-box");

    const openTriggers = document.querySelectorAll("[data-open-download]");
    if (fabBtn && modal) {
        let returnFocus = null;
        const openModal = (trigger) => {
            returnFocus = trigger || document.activeElement;
            modal.classList.remove("hidden");
            resultBox.innerHTML = "";
            modalInput.value = "";
            modalInput.style.borderColor = "";
            modalSubmit.disabled = false;
            modalSubmit.textContent = SUBMIT_LABEL;
            window.setTimeout(() => modalInput.focus(), 30);
        };
        const closeModal = () => {
            if (modal.classList.contains("hidden")) return;
            modal.classList.add("hidden");
            if (returnFocus?.isConnected) returnFocus.focus();
        };

        // Open from the sidebar button or the mobile floating button
        openTriggers.forEach((trigger) => {
            trigger.addEventListener("click", () => openModal(trigger));
        });

        // Close Modal via button
        closeBtn.addEventListener("click", closeModal);

        // Close Modal clicking outside content box
        modal.addEventListener("click", (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeModal();
        });

        // Accept the public URL forms supported by the server-side provider registry.
        modalInput.addEventListener("input", (e) => {
            const val = e.target.value.trim();
            const supported = /^(https?:\/\/)?(open\.spotify\.com|music\.youtube\.com|(?:www\.|m\.)?youtube\.com|youtu\.be)\//i.test(val);
            if (val.length > 0 && !supported) {
                modalInput.style.borderColor = "var(--danger)";
                modalSubmit.disabled = true;
                modalSubmit.textContent = "Unsupported URL";
            } else {
                modalInput.style.borderColor = "";
                modalSubmit.disabled = false;
                modalSubmit.textContent = SUBMIT_LABEL;
            }
        });

        // Async Ingestion Dispatched from Modal Form
        modalForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const targetUrl = modalInput.value.trim();
            const isPlaylist = /(?:\/playlist[/?]|open\.spotify\.com\/playlist\/)/i.test(targetUrl);
            const metadataStartedAt = Date.now();
            const updateMetadataElapsed = () => {
                const elapsed = Math.max(0, Math.floor((Date.now() - metadataStartedAt) / 1000));
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                const elapsedNode = document.getElementById("modal-metadata-elapsed");
                if (elapsedNode) {
                    elapsedNode.textContent = minutes
                        ? `${minutes}m ${seconds}s elapsed`
                        : `${seconds}s elapsed`;
                }
            };
            resultBox.innerHTML = `<div class="success-message"><span class="spinner" style="border-top-color:var(--primary);"></span> ${isPlaylist ? "Fetching the complete playlist track list" : "Analyzing metadata"}… <small id="modal-metadata-elapsed">0s elapsed</small>${isPlaylist ? "<br><small>Large Spotify playlists can remain at this stage for several minutes. Downloads are created after metadata finishes.</small>" : ""}</div>`;
            const metadataTimer = window.setInterval(updateMetadataElapsed, 1000);
            modalSubmit.disabled = true;

            try {
                const response = await fetch("/api/downloads", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ url: targetUrl }),
                });
                
                const data = await response.json();
                if (!response.ok) {
                    const detail = data.detail;
                    throw new Error(
                        typeof detail === "string"
                            ? detail
                            : detail?.message || "Ingestion failed.",
                    );
                }

                if (data.summary) {
                    resultBox.innerHTML = `
                        <div class="success-message" style="margin-top:12px;">
                            <strong>Playlist added to the queue</strong><br>
                            Tracks queued: ${data.summary.queued}<br>
                            Already in library: ${data.summary.owned}
                        </div>
                    `;
                } else if (data.status === "owned") {
                    resultBox.innerHTML = `<div class="success-message" style="margin-top:12px;">This track is already in your library.</div>`;
                } else {
                    resultBox.innerHTML = `<div class="success-message" style="margin-top:12px;">Download queued.</div>`;
                }
                
                // Keep window open briefly so status can be reviewed, then close auto
                setTimeout(closeModal, 2500);

            } catch (err) {
                const message = document.createElement("div");
                message.className = "error-message";
                message.textContent = err.message;
                resultBox.replaceChildren(message);
            } finally {
                window.clearInterval(metadataTimer);
                modalSubmit.disabled = false;
                modalSubmit.textContent = SUBMIT_LABEL;
            }
        });
    }
});
