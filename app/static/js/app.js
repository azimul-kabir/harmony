// Shared JavaScript for Harmony

document.addEventListener("DOMContentLoaded", () => {
    const miniPlayer = document.getElementById("global-mini-player");
    if (!miniPlayer) return;

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
            // Drive the UI using the first active task
            const task = activeTasks[0]; 
            const finished = task.completed + task.failed + task.skipped;
            const percent = task.total === 0 ? 0 : (finished / task.total) * 100;

            // Prioritize showing the specific track downloading, fallback to task name
            titleEl.textContent = task.current ? task.current : task.name;
            statusEl.innerHTML = task.status.toUpperCase() === "RUNNING" 
                ? '<span class="spinner" style="width:10px; height:10px; border-width:2px; margin-right:4px;"></span> Downloading'
                : 'Queued';
            
            progressFill.style.width = `${percent}%`;
            countEl.textContent = `${finished} / ${task.total}`;

            // Slide up the player
            miniPlayer.classList.remove("hidden");
        } else {
            // Slide down and hide
            miniPlayer.classList.add("hidden");
        }
    };
});
