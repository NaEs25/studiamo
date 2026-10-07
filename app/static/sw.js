// Everything is served network-first (see the fetch handler), so a changed asset reaches users
// without a bump. Bumping still clears out caches left by older versions of this worker.
const CACHE_NAME = 'studiamo-pwa-v14';
const ASSETS_TO_CACHE = [
  '/app',
  '/static/css/style.css',
  '/static/css/fonts.css',
  '/static/vendor/fonts/outfit-v15-latin.woff2',
  '/static/vendor/fonts/outfit-v15-latin-ext.woff2',
  '/static/vendor/lucide-1.48.0.min.js',
  '/static/vendor/marked-12.0.2.min.js',
  '/static/vendor/dompurify-3.1.5.min.js',
  '/static/vendor/turndown-7.2.0.js',
  '/static/js/app.js',
  '/static/js/core.js',
  '/static/js/auth.js',
  '/static/js/goals.js',
  '/static/js/quiz.js',
  '/static/js/settings.js',
  '/static/js/videos.js',
  '/static/manifest.json',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch(err => {
        console.warn('[SW] Cache addAll partial failure:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch handler: bypass for API and external cross-origin requests (e.g. analytics).
// Everything else is network-first, falling back to the cache only when offline. Static assets
// used to be stale-while-revalidate, which paired a freshly deployed page with the previous
// deploy's CSS and JS for one load, so the page rendered unstyled or with handlers missing.
// The server sends these files with no-cache and an ETag, so the network check is usually a
// small 304.
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/') || event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200 && response.type === 'basic') {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        return new Response('Network error', { status: 503, statusText: 'Service Unavailable' });
      })
  );
});

// Push notification receiver
self.addEventListener('push', (event) => {
  let data = { title: 'Studiamo', body: 'You have reviews due!' };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body || 'Active recall reviews are waiting for you!',
    icon: '/static/images/icon-192.png',
    badge: '/static/images/icon-192.png',
    vibrate: [100, 50, 100],
    data: {
      url: data.url || '/',
      log_id: data.log_id || null
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'Studiamo Recall', options)
  );
});

// Handle clicking on notifications
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data && event.notification.data.url ? event.notification.data.url : '/';
  const logId = event.notification.data && event.notification.data.log_id;

  // Counts the tap against the reminder's template. Best effort: a signed-out or offline
  // device just does not count, and it must never delay opening the app.
  if (logId) {
    const body = new URLSearchParams({ log_id: String(logId) });
    event.waitUntil(fetch('/api/notifications/clicked', { method: 'POST', body, credentials: 'same-origin' }).catch(() => {}));
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
