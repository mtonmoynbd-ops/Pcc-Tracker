const CACHE = 'pcc-tracker-v3';
const BASE = 'https://mtonmoynbd-ops.github.io/Pcc-Tracker';

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      // Cache app shell
      return cache.addAll([
        BASE + '/',
        BASE + '/index.html',
      ]).catch(function(){});
    }).then(function() {
      // Fetch data.json and pre-cache all cert/doc images
      return fetch(BASE + '/data.json', {cache:'no-store'}).then(function(res) {
        return res.json();
      }).then(function(data) {
        return caches.open(CACHE).then(function(cache) {
          var urls = [];
          (data.applications || []).forEach(function(app) {
            ['cert_file','form_file','chalan_file','passport_file'].forEach(function(key) {
              if(app[key]) urls.push(BASE + '/' + app[key]);
            });
          });
          // Cache data files
          urls.push(BASE + '/data.json');
          urls.push(BASE + '/userdata.json');
          return Promise.all(urls.map(function(url) {
            return cache.add(url).catch(function(){});
          }));
        });
      }).catch(function(){});
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

  // certs images — cache first, network fallback
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

  // index.html — network first, cache fallback
  if(url.includes('/Pcc-Tracker')) {
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
});
