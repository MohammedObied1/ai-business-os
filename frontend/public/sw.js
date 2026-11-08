// Service worker: installable app + the cashier screen (/pos) keeps opening without internet.
// - /_next/static files are versioned → cache-first.
// - Pages are network-first; the last good copy of each page is kept so /pos (and others already visited) open offline.
// - API calls are never cached here (the POS keeps its own copy of products and queues sales itself).
const CACHE = "bizos-v2";
const SHELL = ["/offline.html", "/icons/icon-192.png", "/manifest.webmanifest", "/pos"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // the API lives on another origin → straight to the network

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })));
    return;
  }

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match("/pos").then((pos) => (url.pathname.startsWith("/pos") && pos) || caches.match("/offline.html")))));
  }
});
