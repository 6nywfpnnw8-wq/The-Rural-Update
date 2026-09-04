const CACHE = 'the-rural-update-v3';
const APP_SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './archive-loader.js',
  './icons/apple-touch-icon.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './the-rural-update-logo.png',
  './archive/catalog.json'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

function isRootDocument(request) {
  if (request.mode !== 'navigate') return false;
  const url = new URL(request.url);
  const scopePath = new URL(self.registration.scope).pathname;
  return url.pathname === scopePath || url.pathname === scopePath + 'index.html';
}

async function injectArchiveLoader(response) {
  if (!response) return response;
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('text/html')) return response;

  let html = await response.text();
  if (!html.includes('archive-loader.js')) {
    html = html.replace('</body>', '<script src="./archive-loader.js"></script>\n</body>');
  }

  const headers = new Headers(response.headers);
  headers.delete('content-length');
  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  if (isRootDocument(event.request)) {
    event.respondWith((async () => {
      try {
        const networkResponse = await fetch(event.request);
        if (networkResponse.ok) {
          const injected = await injectArchiveLoader(networkResponse);
          const cache = await caches.open(CACHE);
          cache.put(event.request, injected.clone());
          return injected;
        }
      } catch (error) {
        // Fall through to cache.
      }

      const cached = await caches.match(event.request) || await caches.match('./index.html');
      if (cached) return injectArchiveLoader(cached);
      return Response.error();
    })());
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(event.request, copy));
          return response;
        }

        if (event.request.mode === 'navigate') {
          return caches.match('./index.html').then(injectArchiveLoader);
        }

        return response;
      })
      .catch(() =>
        caches.match(event.request).then(cached => {
          if (cached) return cached;
          if (event.request.mode === 'navigate') {
            return caches.match('./index.html').then(injectArchiveLoader);
          }
          return Response.error();
        })
      )
  );
});
