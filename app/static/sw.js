const CACHE = 'open-road-pwa-v20';
const CORE = [
  '/',
  '/offline',
  '/offline/my-stuff',
  '/manifest.json',
  '/static/style.css',
  '/sw.js',
  '/static/icon.svg',
  '/static/placeholder.svg',
  '/static/event-signature.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(CORE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isSensitive(pathname) {
  return pathname.startsWith('/admin') ||
         pathname.startsWith('/api/') ||
         pathname.startsWith('/media/') ||
         pathname === '/account' ||
         pathname.startsWith('/booking') ||
         pathname.startsWith('/ticket/') ||
         pathname.startsWith('/scan/') ||
         pathname.startsWith('/my-stuff');
}

function isSafePublicPage(pathname) {
  return pathname === '/' ||
         pathname.startsWith('/destination/') ||
         pathname.startsWith('/trip/') ||
         pathname === '/services' ||
         pathname === '/ticketing' ||
         pathname === '/group-retreats' ||
         pathname === '/search' ||
         pathname === '/contact' ||
         pathname === '/join';
}

async function cacheFresh(request, response) {
  if (!response || !response.ok || response.type === 'opaque') return response;
  const cache = await caches.open(CACHE);
  await cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const pathname = url.pathname;
  const isNavigation = request.mode === 'navigate';
  const isStatic = pathname.startsWith('/static/') || pathname === '/manifest.json';

  // Static assets are cache-first. This is what keeps the installed app looking
  // like an app even when the network disappears.
  if (isStatic) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(r => cacheFresh(request, r)))
    );
    return;
  }

  // The authenticated My Stuff page deliberately falls back to a local-only
  // IndexedDB workspace instead of serving somebody's cached private HTML.
  if (isNavigation && (pathname === '/my-stuff' || pathname.startsWith('/my-stuff/'))) {
    event.respondWith(
      fetch(request).catch(() => caches.match('/offline/my-stuff'))
    );
    return;
  }

  // Offline entrypoint.
  if (isNavigation && pathname === '/offline') {
    event.respondWith(caches.match('/offline'));
    return;
  }

  // Home and other public pages get network-first freshness, then offline cache.
  if (isNavigation && (isSafePublicPage(pathname) || pathname === '/')) {
    event.respondWith(
      fetch(request)
        .then(response => cacheFresh(request, response))
        .catch(() => caches.match(request).then(cached => cached || caches.match('/offline')))
    );
    return;
  }

  // Never cache sensitive/private server responses.
  if (isSensitive(pathname)) return;

  // For other GET requests, prefer the network but keep a harmless public copy.
  event.respondWith(
    fetch(request)
      .then(response => cacheFresh(request, response))
      .catch(() => caches.match(request))
  );
});
