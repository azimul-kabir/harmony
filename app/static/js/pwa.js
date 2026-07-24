// Register Harmony's offline shell. Browsers require HTTPS, except on localhost.
if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js").catch((error) => {
            console.warn("Harmony service worker registration failed:", error);
        });
    });
}
