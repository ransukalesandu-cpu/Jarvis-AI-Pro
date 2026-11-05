// Service worker: makes the client installable and lets the shell load
// instantly; data always comes live from the hub over the WebSocket.
const CACHE = "jarvis-shell-v1";
const SHELL = ["/static/theme.css", "/static/app.css", "/static/app.js", "/static/theme.js",
  "/static/orb.js", "/static/governor.js", "/static/audio.js", "/static/audio-worklet.js",
  "/static/icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !url.pathname.startsWith("/static/")) return;   // never cache files/API
  e.respondWith(fetch(e.request).then((res) => {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return res;
  }).catch(() => caches.match(e.request)));
});
