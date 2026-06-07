{% load static %}// ForensiQ — Service Worker (PWA básica, Fase 3).
// Precache da casca + network-first para estáticos (cache só como fallback
// offline). NUNCA cacheia prova/dados mutáveis (/api, /media, /v/, /pdf) —
// imutabilidade forense ISO/IEC 27037.
//
// NOTA: a estratégia para /static/ é NETWORK-FIRST de propósito. Os ficheiros
// estáticos não têm hash no nome (sem ManifestStaticFilesStorage), pelo que um
// cache-first servia versões antigas de CSS/JS indefinidamente (o utilizador
// via correções "não aplicadas" mesmo após Ctrl+F5). Network-first garante
// frescura quando há rede e mantém a app utilizável offline pelo cache.
// Bump da versão expurga o cache anterior no activate.
const CACHE = 'forensiq-shell-v2';
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

  // Estáticos: network-first (atualiza o cache) com fallback ao cache offline.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return resp;
        })
        .catch(() => caches.match(req))
    );
  }
});
