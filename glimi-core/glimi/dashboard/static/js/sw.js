/* Glimi service worker — minimal app-shell cache, versioned by asset_v.
 *
 * Strategy (see analysis/reactions_threads_mobile_plan.md §7b):
 *  - Versioned cache name tied to ?v=<asset_v> (passed at registration), so a
 *    deploy (new asset_v) creates a fresh cache and the old one is purged on
 *    activate — never serves a frozen old client.
 *  - network-first for HTML / navigations (always try the live page; fall back
 *    to a cached shell only when offline) so a logged-in user never gets a stale
 *    or wrong-auth page from cache.
 *  - stale-while-revalidate for same-origin JS+CSS under /static/: serve the
 *    cached copy fast, but always re-fetch in the background and overwrite the
 *    cache, so a deploy is picked up on the NEXT load even within the same SW
 *    generation (never frozen on old chat.js/dashboard.js/css). Other static
 *    assets (images/fonts/manifest, cache-busted by ?v=) stay cache-first.
 *  - NEVER touch chat data: the chat REST endpoints (/community/.../chat/...),
 *    any /api/ call, and WebSockets are pass-through (no caching). Chat is live
 *    data; caching it would show stale conversations.
 */
'use strict';

// Derive the version from this script's own URL (?v=<asset_v>), set at register.
var SW_VERSION = (function () {
  try {
    var u = new URL(self.location.href);
    return u.searchParams.get('v') || 'dev';
  } catch (e) {
    return 'dev';
  }
})();
var CACHE_NAME = 'glimi-shell-' + SW_VERSION;

// The app shell — versioned static assets that are safe to precache. Chat data
// is deliberately absent. Each is fetched with the same ?v= so the cached copy
// matches the running client.
var SHELL = [
  '/static/css/tokens.css?v=' + SW_VERSION,
  '/static/css/base.css?v=' + SW_VERSION,
  '/static/css/chat.css?v=' + SW_VERSION,
  '/static/js/chat.js?v=' + SW_VERSION,
  '/static/manifest.webmanifest?v=' + SW_VERSION,
  '/static/icons/icon-192.png?v=' + SW_VERSION,
  '/static/icons/icon-512.png?v=' + SW_VERSION
];

self.addEventListener('install', function (event) {
  // Precache best-effort: a single missing asset must not fail the whole install.
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return Promise.all(SHELL.map(function (url) {
        return cache.add(url).catch(function () { /* skip on failure */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  // Drop every cache that isn't the current version (deploy → fresh client).
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k.indexOf('glimi-shell-') === 0 && k !== CACHE_NAME) {
          return caches.delete(k);
        }
        return null;
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

function isChatData(url) {
  // Live data — never cache. Chat REST + any API + (WS never hits fetch anyway).
  if (url.pathname.indexOf('/api/') !== -1) return true;
  if (url.pathname.indexOf('/chat/') !== -1) return true;  // /community/<id>/chat/*
  return false;
}

self.addEventListener('fetch', function (event) {
  var req = event.request;
  // Only GET is cacheable; everything else passes through untouched.
  if (req.method !== 'GET') return;

  var url;
  try { url = new URL(req.url); } catch (e) { return; }

  // Same-origin only — never intercept cross-origin (avatars/CDN/etc.).
  if (url.origin !== self.location.origin) return;

  // Live chat / API data — pass through (no cache).
  if (isChatData(url)) return;

  // Navigations / HTML pages → network-first, cache fallback when offline.
  var accept = req.headers.get('accept') || '';
  if (req.mode === 'navigate' || accept.indexOf('text/html') !== -1) {
    event.respondWith(
      fetch(req).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || new Response(
            '<!doctype html><meta charset="utf-8"><title>오프라인</title>' +
            '<body style="font-family:sans-serif;padding:2rem;color:#333">' +
            '<h1>오프라인</h1><p>네트워크에 연결되어 있지 않습니다. ' +
            '연결되면 새로고침해 주세요.</p></body>',
            { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          );
        });
      })
    );
    return;
  }

  // Same-origin static assets under /static/.
  if (url.pathname.indexOf('/static/') === 0) {
    // JS + CSS → stale-while-revalidate: serve cache fast, but ALWAYS re-fetch in
    // the background and overwrite the cache, so a deploy is picked up on the next
    // load even within the same SW generation (no frozen old chat.js/css).
    if (/\.(?:js|css)(?:$|\?)/.test(url.pathname + url.search)) {
      event.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
          return cache.match(req).then(function (hit) {
            var network = fetch(req).then(function (resp) {
              // Only cache successful, basic (same-origin) responses.
              if (resp && resp.status === 200 && resp.type === 'basic') {
                return cache.put(req, resp.clone()).then(function () { return resp; });
              }
              return resp;
            }).catch(function () { return hit; });
            // Keep the SW alive until the background refresh + cache.put settle,
            // so the next load actually sees the fresh asset.
            event.waitUntil(network.catch(function () {}));
            // Serve cache immediately if present; otherwise wait on the network.
            return hit || network;
          });
        })
      );
      return;
    }
    // Other static assets (images/fonts/manifest, cache-busted by ?v=) → cache-first.
    event.respondWith(
      caches.match(req).then(function (hit) {
        if (hit) return hit;
        return fetch(req).then(function (resp) {
          // Only cache successful, basic (same-origin) responses.
          if (resp && resp.status === 200 && resp.type === 'basic') {
            var clone = resp.clone();
            caches.open(CACHE_NAME).then(function (cache) { cache.put(req, clone); });
          }
          return resp;
        }).catch(function () { return hit; });
      })
    );
    return;
  }
  // Everything else → default network (no caching).
});
