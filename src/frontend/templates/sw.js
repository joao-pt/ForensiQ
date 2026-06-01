{% load static %}// ForensiQ — Service Worker (PWA básica, Fase 3).
// Precache da casca + cache-first para estáticos. NUNCA cacheia prova/dados
// mutáveis (/api, /media, /v/, /pdf) — imutabilidade forense ISO/IEC 27037.
const CACHE = 'forensiq-shell-v1';
const PRECACHE = [
  '{% static "css/main.css" %}',
  '{% static "css/components/app-shell.css" %}',
  '{% static "css/components/forensic.css" %}',
  '{% static "js/theme-init.js" %}',
  '{% static "js/app-shell.js" %}',
  '{% static "img/favicon.svg" %}'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // tiles OSM, etc. — sempre rede

  // Prova e dados mutáveis: SEMPRE rede, nunca cache (imutabilidade forense).
  if (
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/media') ||
    url.pathname.startsWith('/v/') ||
    url.pathname.includes('/pdf')
  ) {
    return;
  }

  // Estáticos: cache-first com preenchimento.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit ||
        fetch(req).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return resp;
        })
      )
    );
  }
});
