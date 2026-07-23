// Shared JavaScript for Harmony

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

    if (fabBtn && modal) {
        // Open Modal
        fabBtn.addEventListener("click", () => {
            modal.classList.remove("hidden");
            resultBox.innerHTML = "";
            modalInput.value = "";
            modalInput.focus();
        });

        // Close Modal via button
        closeBtn.addEventListener("click", () => {
            modal.classList.add("hidden");
        });

        // Close Modal clicking outside content box
        modal.addEventListener("click", (e) => {
            if (e.target === modal) {
                modal.classList.add("hidden");
            }
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
                modalInput.style.borderColor = "var(--border-input)";
                modalSubmit.disabled = false;
                modalSubmit.textContent = "Start Ingestion";
            }
        });

        // Async Ingestion Dispatched from Modal Form
        modalForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const targetUrl = modalInput.value.trim();
            
            resultBox.innerHTML = '<div class="success-message"><span class="spinner" style="border-top-color:var(--primary);"></span> Analyzing metadata...</div>';
            modalSubmit.disabled = true;

            try {
                const response = await fetch("/api/downloads", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ url: targetUrl }),
                });
                
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "Ingestion thread error.");

                if (data.summary) {
                    resultBox.innerHTML = `
                        <div class="success-message" style="margin-top:12px;">
                            <strong>Playlist ingestion added</strong><br>
                            Tracks Queued: ${data.summary.queued}<br>
                            Duplicates Skipped: ${data.summary.owned}
                        </div>
                    `;
                } else if (data.status === "owned") {
                    resultBox.innerHTML = `<div class="success-message" style="margin-top:12px;">Track verified. Already matches an existing file in library.</div>`;
                } else {
                    resultBox.innerHTML = `<div class="success-message" style="margin-top:12px;">Track ingestion thread created.</div>`;
                }
                
                // Keep window open briefly so status can be reviewed, then close auto
                setTimeout(() => {
                    modal.classList.add("hidden");
                }, 2500);

            } catch (err) {
                resultBox.innerHTML = `<div class="error-message" style="margin-top:12px;">${err.message}</div>`;
            } finally {
                modalSubmit.disabled = false;
                modalSubmit.textContent = "Start Ingestion";
            }
        });
    }
});
