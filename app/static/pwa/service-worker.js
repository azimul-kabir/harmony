const CACHE_VERSION = "harmony-shell-v4";
const APP_SHELL = [
    "/static/css/app.css",
    "/static/js/app.js",
    "/static/js/pwa.js",
    "/static/pwa/offline.html",
    "/static/pwa/icon-192.png",
    "/static/pwa/icon-512.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_VERSION)
            .then((cache) => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys
                    .filter((key) => key !== CACHE_VERSION)
                    .map((key) => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);

    if (request.method !== "GET" || url.origin !== self.location.origin) {
        return;
    }

    // Only explicitly listed, non-sensitive static shell files are cacheable.
    if (
        url.pathname.startsWith("/api/") ||
        url.pathname.startsWith("/artwork/") ||
        url.pathname === "/health"
    ) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request).catch(() => caches.match("/static/pwa/offline.html"))
        );
        return;
    }

    if (APP_SHELL.includes(url.pathname)) {
        event.respondWith(
            fetch(request).then((response) => {
                    if (response.ok) {
                        const copy = response.clone();
                        caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
                    }
                    return response;
                })
                .catch(() => caches.match(request))
        );
    }
});
