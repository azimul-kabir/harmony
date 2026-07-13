async function loadSources() {
    const response = await fetch("/api/sources");
    const sources = await response.json();

    const container = document.getElementById("sources");

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

    container.innerHTML = sources.map(source => `
        <div class="source-card">

            <div class="source-header">
                <h3>${source.name}</h3>

                <span class="badge ${
                    source.enabled
                        ? "badge-enabled"
                        : "badge-disabled"
                }">
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
                    ${source.last_synced_at ?? "Never"}
                </div>
            </div>

            <div class="source-actions">

                <button
                    class="sync-btn"
                    data-id="${source.id}">
                    Sync Now
                </button>

                <button
                    class="toggle-btn"
                    data-id="${source.id}"
                    data-enabled="${source.enabled}">
                    ${source.enabled ? "Disable" : "Enable"}
                </button>

                <button
                    class="delete-btn"
                    data-id="${source.id}">
                    Delete
                </button>

            </div>

        </div>
    `).join("");

    bindEvents();
}

function bindEvents() {
    document.querySelectorAll(".sync-btn").forEach(button => {
        button.addEventListener("click", syncSource);
    });

    document.querySelectorAll(".toggle-btn").forEach(button => {
        button.addEventListener("click", toggleSource);
    });

    document.querySelectorAll(".delete-btn").forEach(button => {
        button.addEventListener("click", deleteSource);
    });
}

async function deleteSource(event) {
    const id = event.target.dataset.id;

    if (!confirm("Delete this source?")) {
        return;
    }

    const response = await fetch(
        `/api/sources/${id}`,
        {
            method: "DELETE",
        },
    );

    if (!response.ok) {
        alert("Delete failed.");
        return;
    }

    await loadSources();
}


async function toggleSource(event) {
    const id = event.target.dataset.id;
    const enabled = event.target.dataset.enabled === "true";

    const response = await fetch(`/api/sources/${id}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            enabled: !enabled,
        }),
    });

    if (!response.ok) {
        alert("Update failed.");
        return;
    }

    await loadSources();
}


async function syncSource(event) {
    const id = event.target.dataset.id;

    event.target.disabled = true;
    event.target.textContent = "Syncing...";

    const response = await fetch(
        `/api/sources/${id}/sync`,
        {
            method: "POST",
        },
    );

    if (!response.ok) {
        alert("Sync failed.");
    }

    await loadSources();
}

document
    .getElementById("add-source-form")
    .addEventListener(
        "submit",
        addSource,
    );

loadSources();


async function addSource(event) {
    event.preventDefault();

    const input = document.getElementById("source-url");

    const response = await fetch(
        "/api/sources",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                spotify_url: input.value,
            }),
        },
    );

    if (!response.ok) {
        alert("Unable to add source.");
        return;
    }

    input.value = "";

    await loadSources();
}