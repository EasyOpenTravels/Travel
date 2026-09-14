const CACHE = 'open-road-pwa-v50';
const CORE = [
  '/',
  '/offline',
  '/offline/my-stuff',
  '/manifest.json',
  '/static/style.css?v=50',
  '/static/icon.svg',
  '/static/placeholder.svg',
  '/static/event-signature.png'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isSensitive(pathname) {
  return pathname.startsWith('/admin') || pathname.startsWith('/api/') || pathname.startsWith('/media/') ||
         pathname === '/account' || pathname.startsWith('/booking') || pathname.startsWith('/ticket/') ||
         pathname.startsWith('/scan/') || pathname.startsWith('/my-stuff');
}

function isSafePublicPage(pathname) {
  return pathname === '/' || pathname.startsWith('/destination/') || pathname.startsWith('/trip/') ||
         pathname === '/services' || pathname === '/ticketing' || pathname === '/group-retreats' ||
         pathname === '/search' || pathname === '/contact' || pathname === '/join';
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

  // NEVER cache the service-worker script itself. This is important so future
  // deployments can actually replace the worker and clear stale application code.
  if (pathname === '/sw.js') {
    event.respondWith(fetch(request, {cache:'no-store'}));
    return;
  }

  const isNavigation = request.mode === 'navigate';
  const isStatic = pathname.startsWith('/static/') || pathname === '/manifest.json';
  if (isStatic) {
    event.respondWith(
      fetch(request, {cache:'no-store'}).then(r => cacheFresh(request,r)).catch(() => caches.match(request))
    );
    return;
  }

  if (isNavigation && (pathname === '/my-stuff' || pathname.startsWith('/my-stuff/'))) {
    event.respondWith(
      fetch(request).then(response => cacheFresh(request,response)).catch(() => caches.match(request).then(cached => cached || caches.match('/offline/my-stuff')))
    );
    return;
  }

  if (isNavigation && pathname === '/offline') {
    event.respondWith(caches.match('/offline'));
    return;
  }

  if (isNavigation && (isSafePublicPage(pathname) || pathname === '/')) {
    event.respondWith(
      fetch(request).then(response => cacheFresh(request,response)).catch(() => caches.match(request).then(cached => cached || caches.match('/offline')))
    );
    return;
  }

  if (isSensitive(pathname)) return;

  event.respondWith(
    fetch(request).then(response => cacheFresh(request,response)).catch(() => caches.match(request).then(cached => cached || caches.match('/offline')))
  );
});
