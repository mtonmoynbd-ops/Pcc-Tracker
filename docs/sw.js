const CACHE = 'pcc-tracker-v1';
const OFFLINE_URLS = [
  '/Pcc-Tracker/',
  '/Pcc-Tracker/index.html',
];

// Install: cache the app shell
self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll(OFFLINE_URLS);
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE; })
            .map(function(k) { return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

// Fetch: network first, fallback to cache
self.addEventListener('fetch', function(e) {
  // Only handle GET requests
  if (e.request.method !== 'GET') return;

  const url = e.request.url;

  // data.json: network first, cache fallback
  if (url.includes('data.json')) {
    e.respondWith(
      fetch(e.request).then(function(res) {
        const clone = res.clone();
        caches.open(CACHE).then(function(cache) {
          cache.put(e.request, clone);
        });
        return res;
      }).catch(function() {
        return caches.match(e.request);
      })
    );
    return;
  }

  // App shell (index.html): network first, cache fallback
  if (url.includes('/Pcc-Tracker/') && !url.includes('certs/')) {
    e.respondWith(
      fetch(e.request).then(function(res) {
        const clone = res.clone();
        caches.open(CACHE).then(function(cache) {
          cache.put(e.request, clone);
        });
        return res;
      }).catch(function() {
        return caches.match(e.request) || caches.match('/Pcc-Tracker/index.html');
      })
    );
    return;
  }

  // Certificate/doc images: cache first
  if (url.includes('certs/')) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        return cached || fetch(e.request).then(function(res) {
          const clone = res.clone();
          caches.open(CACHE).then(function(cache) {
            cache.put(e.request, clone);
          });
          return res;
        });
      })
    );
    return;
  }
});
