const CACHE = 'pcc-tracker-v2';
const BASE = 'https://mtonmoynbd-ops.github.io/Pcc-Tracker';

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll([
        BASE + '/',
        BASE + '/index.html',
        BASE + '/data.json',
        BASE + '/userdata.json',
      ]).catch(function(){});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(k){return k!==CACHE;}).map(function(k){return caches.delete(k);}));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  if(e.request.method !== 'GET') return;
  const url = e.request.url;

  // data.json & userdata.json — network first, cache fallback
  if(url.includes('data.json') || url.includes('userdata.json')) {
    e.respondWith(
      fetch(e.request, {cache:'no-store'}).then(function(res) {
        const clone = res.clone();
        caches.open(CACHE).then(function(c){c.put(e.request, clone);});
        return res;
      }).catch(function() {
        return caches.match(e.request);
      })
    );
    return;
  }

  // index.html — network first, cache fallback
  if(url.includes('/Pcc-Tracker') && !url.includes('certs/')) {
    e.respondWith(
      fetch(e.request).then(function(res) {
        const clone = res.clone();
        caches.open(CACHE).then(function(c){c.put(e.request, clone);});
        return res;
      }).catch(function() {
        return caches.match(e.request) || caches.match(BASE+'/index.html');
      })
    );
    return;
  }

  // certs images — cache first
  if(url.includes('certs/')) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        return cached || fetch(e.request).then(function(res) {
          const clone = res.clone();
          caches.open(CACHE).then(function(c){c.put(e.request, clone);});
          return res;
        });
      })
    );
    return;
  }
});
