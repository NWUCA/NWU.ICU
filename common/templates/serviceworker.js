// {% load static %}

const cacheName = 'NWU.ICU-v1';
const appShellFiles = [
    'https://unpkg.com/vue@3.0.9/dist/vue.global.js',
]

self.addEventListener('install', (e) => {
    console.log('[Service Worker] Install');
    e.waitUntil((async () => {
        const cache = await caches.open(cacheName);
        console.log('[Service Worker] Caching all: app shell and content');
        await cache.addAll(appShellFiles);
    })());
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        return true;
    })());
});

self.addEventListener('fetch', (e) => {
    console.log(e.request)
    if (e.request.url.startsWith('chrome-extension') || e.request.method !== 'GET' || e.request.destination === 'document') {
        console.log(`[Service Worker] Skipping dealing with resource: ${e.request.url}`);
        return
    }
    e.respondWith((async () => {
        const r = await caches.match(e.request);
        console.log(`[Service Worker] Fetching resource: ${e.request.url}`);
        if (r) {
            console.log(`[Service Worker] Using cached resource: ${e.request.url}`);
            return r;
        }
        const response = await fetch(e.request);
        const cache = await caches.open(cacheName);
        console.log(`[Service Worker] Caching new resource: ${e.request.url}`);
        await cache.put(e.request, response.clone());
        return response;
    })());
});
