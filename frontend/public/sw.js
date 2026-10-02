/*
 * GlobeLens service worker.
 *
 * Scope is deliberately narrow. News data must never be served stale: a
 * cached intelligence summary reads as current fact, and this app exists to
 * tell readers what is true right now. So the API is network-only with no
 * fallback, and only immutable static assets are cached.
 */

const VERSION = "gl-lens-v2";
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;

// Never cache these: either live data or an error page that would masquerade
// as real content.
const NEVER_CACHE = ["/api/", "/graphql", "_next/webpack-hmr"];

const CURRENT = new Set([SHELL, ASSETS]);

self.addEventListener("install", (event) => {
  // No precache. The shell needs session cookies and live API calls, so
  // caching it would only serve a login page offline.
  // skipWaiting must be inside waitUntil, otherwise the install can be marked
  // complete before it takes effect.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            // Compare against the exact current names. Testing
            // `key.endsWith(VERSION)` looks right but never matches
            // "gl-lens-v1-assets", so it deleted the live cache on every
            // activation and the asset cache never retained anything.
            .filter((key) => key.startsWith("gl-lens-") && !CURRENT.has(key))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

const OFFLINE_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline — GlobeLens</title>
<style>body{background:#030712;color:#e5e7eb;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1.5rem}
div{max-width:24rem;text-align:center}h1{font-size:1.25rem;margin:0 0 .75rem}
p{font-size:.875rem;color:#9ca3af;line-height:1.6;margin:0 0 1rem}
a{color:#60a5fa;font-size:.875rem}</style></head><body><div>
<h1>You are offline</h1>
<p>GlobeLens could not reach the network. Event intelligence is served live
and never cached, so nothing is shown here rather than risk presenting stale
reporting as current.</p>
<a href="/">Try again</a></div></body></html>`;

function offlineResponse() {
  return new Response(OFFLINE_PAGE, {
    status: 503,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function isAsset(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    /\.(?:svg|png|jpg|jpeg|webp|woff2?|ico|css|js)$/.test(url.pathname)
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((prefix) => url.pathname.startsWith(prefix))) return;

  // Static build output is content-hashed, so a hit is always correct.
  if (isAsset(url)) {
    event.respondWith(
      caches.open(ASSETS).then(async (cache) => {
        const hit = await cache.match(request);
        if (hit) return hit;
        try {
          const response = await fetch(request);
          if (response.ok && response.type === "basic") {
            cache.put(request, response.clone());
          }
          return response;
        } catch (err) {
          // Offline with no cache entry: let the failure surface rather than
          // substituting a stale page.
          throw err;
        }
      })
    );
    return;
  }

  // Navigations: network first, so a deploy is picked up immediately.
  // On failure serve an inline page rather than a cached route. GlobeLens
  // deliberately does not cache news responses, so there is nothing
  // trustworthy to show and no stale intelligence to risk presenting.
  if (request.mode === "navigate") {
    // A prerendered route like "/" is also in the browser's own HTTP cache, so
    // a plain fetch() while offline can be answered from that cache and
    // succeed. The reader would then see an empty-looking shell that reads as
    // "no news" rather than "no connection". Checking onLine first makes the
    // offline state explicit; cache:"no-store" stops the HTTP cache from
    // masking it if onLine is optimistic.
    event.respondWith(
      (self.navigator.onLine === false
        ? Promise.reject(new Error("offline"))
        : fetch(request, { cache: "no-store" })
      ).catch(() => offlineResponse())
    );
  }
});