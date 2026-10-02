// Read-only offline cache for field mode: starred records and lookups are served from the last good response when the network is gone.
// Writes are never cached here; queued quick-adds are replayed by the app with idempotent client ids.
const CACHE = 'trg-field-v1'
const READ = [/^\/api\/stars/, /^\/api\/lookup\//]

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())))

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== location.origin || !READ.some((r) => r.test(url.pathname))) return
  e.respondWith(
    fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)) }
      return res
    }).catch(() => caches.match(e.request).then((hit) => hit || new Response(JSON.stringify({ detail: 'Offline and not cached' }), { status: 503, headers: { 'Content-Type': 'application/json' } }))),
  )
})
