(() => {
  "use strict";
  const statusRoot = document.getElementById("provider-status");
  const result = document.getElementById("provider-result");
  const escapeHtml = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  async function refreshStatus() {
    try {
      const response = await fetch("/api/providers/status");
      const data = await response.json();
      statusRoot.innerHTML = data.providers.map((provider) => `<div class="panel provider-card">
        <h2>${escapeHtml(provider.provider)}</h2>
        <dl><dt>Available</dt><dd>${provider.available ? "Yes" : "No"}</dd>
        <dt>Rate limit</dt><dd>${escapeHtml(provider.rate_limit.requests_per_second)} req/s</dd>
        <dt>Cache</dt><dd>${escapeHtml(provider.cache.fresh_entries)} fresh / ${escapeHtml(provider.cache.stale_entries)} stale</dd>
        <dt>Hits / misses</dt><dd>${escapeHtml(provider.cache.hits)} / ${escapeHtml(provider.cache.misses)}</dd>
        <dt>Last request</dt><dd>${escapeHtml(provider.last_request?.operation)}</dd>
        <dt>Last error</dt><dd>${escapeHtml(provider.last_error?.code)}</dd>
        <dt>Latency</dt><dd>${provider.search_latency_ms == null ? "—" : `${Number(provider.search_latency_ms).toFixed(1)} ms`}</dd></dl>
      </div>`).join("");
    } catch (_) { statusRoot.innerHTML = '<div class="panel">Provider status unavailable.</div>'; }
  }

  document.getElementById("provider-search").addEventListener("submit", async (event) => {
    event.preventDefault(); result.textContent = "Searching…";
    try {
      const response = await fetch("/api/providers/test-search", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
        provider: document.getElementById("provider-name").value, entity_type: document.getElementById("provider-entity").value,
        query: document.getElementById("provider-query").value, limit: 10
      })});
      const data = await response.json();
      result.textContent = JSON.stringify(data, null, 2);
    } catch (_) { result.textContent = "Search failed before a response was received."; }
    await refreshStatus();
  });
  refreshStatus();
})();
