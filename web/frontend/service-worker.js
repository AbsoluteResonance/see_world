/* See World PWA Service Worker */
const CACHE_NAME = "see-world-v4";

const PRECACHE_URLS = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/js/upload.js',
  '/static/js/gallery.js',
  '/static/js/viewer3d.js',
];

// Install — pre-cache core assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — cache-first for static, network-first for API
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API requests — network first
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  // Static assets — cache first
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
